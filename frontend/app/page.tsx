"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ youtube_url: youtubeUrl }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail?.[0]?.msg || "Failed to load tape");
      }

      const data = await response.json();
      router.push(`/jobs/${data.job_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setIsSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-[#0B0D0F] text-[#EDEAE3] flex flex-col items-center justify-center px-6">
      <div className="max-w-2xl w-full">
        {/* Eyebrow / system label */}
        <div className="flex items-center gap-2 mb-6 font-mono text-xs tracking-[0.2em] text-[#8A857A]">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              isSubmitting ? "bg-[#FF3B30] animate-pulse" : "bg-[#3A3D42]"
            }`}
          />
          <span>REC ENGINE — DECK 01</span>
        </div>

        <h1 className="text-5xl sm:text-6xl font-medium leading-[1.05] mb-4 tracking-tight">
          Feed it a tape.
          <br />
          <span className="text-[#8A857A]">Get back the takes.</span>
        </h1>

        <p className="text-[#8A857A] text-base mb-10 max-w-md">
          Drop in a YouTube URL. The deck extracts the audio, finds the
          moments worth cutting, and hands you back finished clips.
        </p>

        {/* Deck loader */}
        <form onSubmit={handleSubmit}>
          <div
            className={`relative border rounded-none transition-colors ${
              isSubmitting
                ? "border-[#FF3B30]"
                : "border-[#2A2D31] hover:border-[#3A3D42]"
            } bg-[#111316]`}
          >
            {/* Perforation strip */}
            <div className="absolute left-0 top-0 bottom-0 w-6 flex flex-col justify-around items-center border-r border-[#2A2D31]">
              {Array.from({ length: 8 }).map((_, i) => (
                <span
                  key={i}
                  className="w-1.5 h-1.5 rounded-full bg-[#2A2D31]"
                />
              ))}
            </div>

            <div className="pl-12 pr-4 py-5 flex items-center gap-4">
              <input
                type="text"
                required
                placeholder="youtube.com/watch?v=..."
                value={youtubeUrl}
                onChange={(e) => setYoutubeUrl(e.target.value)}
                disabled={isSubmitting}
                className="flex-1 bg-transparent outline-none placeholder:text-[#4A4D51] font-mono text-sm"
              />
              <span className="font-mono text-xs text-[#4A4D51] hidden sm:block">
                MAX 20:00
              </span>
            </div>
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            className="mt-4 w-full sm:w-auto px-8 py-3 bg-[#EDEAE3] text-[#0B0D0F] font-medium tracking-tight hover:bg-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {isSubmitting ? "Loading tape..." : "Load & cut"}
          </button>

          {error && (
            <p className="mt-4 font-mono text-sm text-[#FF3B30]">
              ERR: {error}
            </p>
          )}
        </form>

        {/* Footer strip */}
        <div className="mt-16 pt-6 border-t border-[#1C1E22] flex justify-between font-mono text-[11px] text-[#4A4D51] tracking-wide">
          <span>WHISPER · TRANSCRIBE</span>
          <span>LLAMA 3.3 · ANALYZE</span>
          <span>FFMPEG · CUT</span>
        </div>
      </div>
    </main>
  );
}