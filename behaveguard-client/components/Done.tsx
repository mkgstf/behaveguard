"use client";

export default function Done() {
  return (
    <div className="flex-1 flex items-center justify-center px-6">
      <div className="text-center fade-up">
        <div className="font-mono-tight text-3xl mb-3 text-text">
          thank you<span className="text-amber">.</span>
        </div>
        <p className="text-muted text-sm">Your session has been recorded. You can close this tab.</p>
      </div>
    </div>
  );
}
