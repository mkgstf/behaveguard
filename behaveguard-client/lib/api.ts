import { Profile, SessionData } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
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
  profiles: () => request<Profile[]>("/profiles?include_blacklisted=true"),
  createProfile: (label: string) => request<Profile>("/profiles", { method: "POST", body: JSON.stringify({ label }) }),
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
}

export interface VerificationResult {
  model_version: string;
  match: boolean;
  best: CandidateResult;
  candidates: CandidateResult[];
  threshold: number;
  margin: number;
  review_sample_id: string;
  feedback_status: "awaiting_feedback" | "pending" | "approved" | "rejected";
  detail?: { category: string; similarity: number; feature_count: number }[];
}

export interface EnrollmentResult {
  session_id: string;
  profile: Profile;
  training: { session_count: number; profile_count: number; svm_trained: boolean; version?: string };
  neural: { trained: boolean; reason?: string; loss?: number; epochs?: number };
}

export interface AdminAnalytics {
  summary: { profiles: number; active_profiles: number; sessions: number; verifications: number; review_samples_available: number };
  profiles: Profile[];
  similarity_labels: string[];
  similarity_matrix: (number | null)[][];
  model: { version: string; session_count: number; profile_count: number; svm_trained: boolean; neural_ready: boolean; strategy: string };
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
  neural: { trained: boolean; reason?: string; loss?: number; epochs?: number };
  included_review_samples: number;
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
