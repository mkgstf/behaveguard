import { Profile, SessionData } from "./types";
import { getAccessToken, refreshAccessToken } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api/v1";

async function request<T>(path: string, init?: RequestInit, retried = false): Promise<T> {
  const token = getAccessToken();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  // A 401 here means the access token expired mid-session (it's a 15-minute
  // token) — refresh once and retry transparently rather than surfacing the
  // failure to the caller. If refresh itself fails (revoked/expired refresh
  // token), fall through to the normal error path below.
  if (response.status === 401 && !retried) {
    const newToken = await refreshAccessToken();
    if (newToken) return request<T>(path, init, true);
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export const api = {
  ping: () => request<{ status: string }>("/ping"),
  health: () => request<{ status: string; model: unknown; redis: boolean }>("/health"),
  profiles: () => request<Profile[]>("/profiles?include_blacklisted=true"),
  myStats: () => request<MyStats>("/profiles/me/stats"),
  adminClaimToken: (profileId: string) => request<{ profile_id: string; token: string }>(`/admin/profiles/${profileId}/claim-token`, { method: "POST" }),
  createProfile: (label: string) => request<Profile>("/profiles", { method: "POST", body: JSON.stringify({ label }) }),
  claimProfile: (token: string) => request<Profile>("/profiles/claim", { method: "POST", body: JSON.stringify({ token }) }),
  blacklist: (id: string, blacklisted: boolean) => request<Profile>(`/profiles/${id}`, { method: "PATCH", body: JSON.stringify({ blacklisted }) }),
  deleteProfile: (id: string) => request<void>(`/profiles/${id}`, { method: "DELETE" }),
  enroll: (id: string, session: SessionData) => request<EnrollmentResult>(`/profiles/${id}/enroll`, { method: "POST", body: JSON.stringify({ session }) }),
  verify: (id: string, session: SessionData) => request<VerificationResult>(`/verify/${id}`, { method: "POST", body: JSON.stringify({ session }) }),
  identify: (profileIds: string[], session: SessionData) => request<VerificationResult>("/identify", { method: "POST", body: JSON.stringify({ profile_ids: profileIds, session }) }),
  submitFeedback: (reviewId: string, predictionCorrect: boolean, trueProfileId: string | null) => request<ReviewSample>(`/review-samples/${reviewId}/feedback`, { method: "POST", body: JSON.stringify({ prediction_correct: predictionCorrect, true_profile_id: trueProfileId }) }),
  analytics: () => request<AdminAnalytics>("/admin/analytics"),
  reviewComparison: (reviewId: string, profileId: string) => request<ReviewComparison>(`/admin/review-samples/${reviewId}/comparison?profile_id=${encodeURIComponent(profileId)}`),
  reviewSample: (reviewId: string, action: "approve" | "reject", profileId?: string) => request<ReviewSample>(`/admin/review-samples/${reviewId}`, { method: "PATCH", body: JSON.stringify({ action, profile_id: profileId || null }) }),
  retrain: () => request<RetrainingResult>("/admin/retrain", { method: "POST" }),
  mergeScan: () => request<MergeScanResult>("/admin/merge/scan", { method: "POST" }),
  mergeEvents: () => request<MergeEvent[]>("/admin/merge/events"),
  revertMerge: (eventId: string) => request<MergeEvent>(`/admin/merge/${eventId}/revert`, { method: "POST" }),
  jobs: () => request<JobStatus[]>("/admin/jobs"),
  securityAlerts: (status: string = "open") => request<SecurityAlert[]>(`/admin/security-alerts?status=${encodeURIComponent(status)}`),
  updateSecurityAlert: (id: string, status: "ack" | "dismissed") => request<SecurityAlert>(`/admin/security-alerts/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
};

export interface CandidateResult {
  profile_id: string;
  label: string;
  similarity: number;
  certainty: number;
  svm_certainty: number;
  neural_certainty: number | null;
  personal_neural_certainty: number | null;
  personal_neural_threshold: number | null;
  personal_neural_match: boolean | null;
  enrollment_count: number;
  behavioral_drift?: {
    status: "available" | "insufficient_baseline";
    level: "stable" | "watch" | "high" | "unknown";
    score: number | null;
    outlier_feature_rate: number | null;
  };
}

export interface VerificationResult {
  model_version: string;
  match: boolean;
  best: CandidateResult;
  candidates: CandidateResult[];
  threshold: number;
  margin: number;
  calibration?: {
    method: string;
    target_far: number | null;
  };
  // Phase 2: 1:1 self-verification no longer creates a review-queue entry
  // (login already answers "who is this"), so these fields no longer exist
  // on the response. `auto_enrolled` reports whether this confident
  // self-check was folded into the profile's training data automatically.
  auto_enrolled?: boolean;
  detail?: { category: string; similarity: number; feature_count: number }[];
  // Phase 4.5: post-verification UX context — aggregate counts only, never
  // another profile's identity. `null` if the context computation failed;
  // the verification itself never fails because of that.
  context?: {
    candidate_pool_size: number;
    close_matches: number;
    total_training_sessions: number;
    own_enrollment_count: number;
  } | null;
}

export interface SessionBehaviorMetrics {
  wpm: number | null;
  dwell_ms: number | null;
  flight_ms: number | null;
  iki_ms: number | null;
  rhythm_cv: number | null;
  backspace_rate: number | null;
  mouse_speed_pxs: number | null;
  click_error_px: number | null;
  target_time_ms: number | null;
  drag_duration_ms: number | null;
  drag_success_rate: number | null;
  tracking_error_px: number | null;
  tremor_px: number | null;
}

export interface MyStatsCard {
  overall: number;
  rank: "S" | "A" | "B" | "C" | "D";
  ratings: Record<string, number>;
  missing_ratings: string[];
  population_size: number;
}

export interface MyStats {
  profile: Profile;
  latest: ({ session_id: string; collected_at: string } & SessionBehaviorMetrics) | null;
  history: ({ session_id: string; collected_at: string } & SessionBehaviorMetrics)[];
  card: MyStatsCard | null;
}

export interface EnrollmentResult {
  session_id: string;
  profile: Profile;
  training: { session_count: number; profile_count: number; svm_trained: boolean; version?: string };
  // Phase 3: the neural fusion retrain no longer blocks the enroll response —
  // it's queued for the background worker instead. Look this id up via
  // GET /admin/jobs (or JobStatus) to see when it's actually done.
  neural_retrain_job_id: string;
}

export interface AdminAnalytics {
  summary: { profiles: number; active_profiles: number; sessions: number; verifications: number; review_samples_available: number };
  profiles: Profile[];
  similarity_labels: string[];
  similarity_matrix: (number | null)[][];
  model: {
    version: string;
    session_count: number;
    profile_count: number;
    svm_trained: boolean;
    neural_ready: boolean;
    neural_status: string;
    neural_profiles: number;
    neural_eligible_profiles: number;
    feature_count: number;
    dropped_feature_count: number;
    calibration: {
      method: string;
      global_threshold: number;
      target_far: number | null;
      observed_far: number | null;
      observed_frr: number | null;
      balanced_accuracy: number | null;
      genuine_trials: number;
      impostor_trials: number;
      unknown_trials: number;
      calibrated_profiles: number;
    };
    strategy: string;
  };
  experiment: null | {
    validity: string;
    warning: string;
    best_model: string;
    best_metrics: { accuracy: number; top3_accuracy: number; verification_auc: number; eer: number };
    best_svm: string;
    tuned_svm: { C: number; gamma: number | string };
    ablations: Record<string, { accuracy: number; verification_auc: number; eer: number }>;
    neural: { trained: boolean; best_validation_accuracy: number; epochs: number };
  };
  personal_neural: PersonalNeuralReport | null;
  profile_cards: ProfileCharacterCard[];
  review_counts: Record<"awaiting_feedback" | "pending" | "approved" | "rejected" | "available" | "ready_for_retrain", number>;
  review_queue: ReviewSample[];
}

export interface PersonalNeuralReport {
  created_at: string;
  validity: string;
  warning: string;
  target_profile_id: string;
  target_label: string;
  genuine_sessions: number;
  impostor_identities: number;
  window_count: number;
  epochs: number;
  operating_threshold: number;
  metrics: {
    roc_auc: number;
    eer: number;
    balanced_accuracy: number;
    genuine_acceptance_rate: number;
    false_rejection_rate: number;
    false_acceptance_rate: number;
    genuine_trials: number;
    impostor_trials: number;
    false_rejections: number;
    false_acceptances: number;
  };
  folds: {
    fold: number;
    threshold: number;
    genuine_score: number;
    genuine_accepted: boolean;
    impostors: { profile_id: string; label: string; score: number; accepted: boolean }[];
    final_loss: number;
  }[];
  genuine_scores: number[];
  impostor_scores: number[];
}

export interface ReviewSample {
  id: string;
  mode: "1to1" | "1toN";
  claimed_profile_id: string | null;
  claimed_label: string | null;
  predicted_profile_id: string | null;
  predicted_label: string | null;
  true_profile_id: string | null;
  true_label: string | null;
  candidate_ids: string[];
  feedback_correct: boolean | null;
  status: "awaiting_feedback" | "pending" | "approved" | "rejected";
  promoted_session_id: string | null;
  created_at: string;
  reviewed_at: string | null;
  trained_at: string | null;
  result: { match: boolean; best: CandidateResult; threshold: number; margin: number };
  comparison: ReviewComparison | null;
}

export interface ReviewComparison {
  profile_id: string;
  profile_label: string;
  overall_coincidence: number;
  enrollment_sessions: number;
  categories: { category: string; similarity: number; feature_count: number }[];
  metrics: { label: string; probe: number | null; profile: number | null; delta_percent: number | null; unit: string }[];
}

export interface RetrainingResult {
  classical: { version?: string; session_count: number; profile_count: number; svm_trained: boolean };
  neural_retrain_job_id: string;
  included_review_samples: number;
}

export interface JobStatus {
  job_id: string;
  type: string;
  reason: string;
  status: "queued" | "running" | "done" | "failed";
  queued_at?: string;
  running_at?: string;
  done_at?: string;
  failed_at?: string;
  result?: { trained: boolean; promoted?: boolean; holdout_accuracy?: number | null; reason?: string };
  error?: string;
}

export interface SecurityAlert {
  id: string;
  profile_id: string | null;
  kind: "replay_suspected" | "far_spike" | "brute_force";
  severity: string;
  details: Record<string, unknown>;
  status: "open" | "ack" | "dismissed";
  created_at: string;
}

export interface ProfileCharacterCard {
  id: string;
  label: string;
  enrollment_count: number;
  overall: number;
  rank: string;
  missing_ratings: string[];
  ratings: Record<string, number>;
  metrics: Record<string, number | null>;
  history: ({ collected_at: string } & Record<string, string | number | null>)[];
}

export interface MergeEvent {
  id: string;
  source_label: string;
  source_user_id: string | null;
  target_profile_id: string;
  similarity_score: number;
  method: string;
  session_ids_moved: string[];
  status: "applied" | "reverted";
  created_at: string;
  reverted_at: string | null;
}

export interface MergeScanResult {
  threshold: number;
  candidates_considered: number;
  merged: { source_label: string; target_label: string; similarity: number; merge_event_id: string }[];
}
