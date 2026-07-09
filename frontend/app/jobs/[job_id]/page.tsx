"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

const STAGES = [
  "PENDING",
  "DOWNLOADING",
  "TRANSCRIBING",
  "ANALYZING",
  "CLIPPING",
  "COMPLETED",
];

const STAGE_LABELS: Record<string, string> = {
  PENDING: "Queued",
  DOWNLOADING: "Pulling source",
  TRANSCRIBING: "Transcribing audio",
  ANALYZING: "Finding the cuts",
  CLIPPING: "Rendering clips",
  COMPLETED: "Done",
  FAILED: "Failed",
};

interface Clip {
  title: string;
  reason?: string;
  start_time: number;
  end_time: number;
  url: string;
  filename: string;
}

interface Job {
  id: string;
  youtube_url: string;
  status: string;
  error_message?: string;
  video_duration_seconds?: number;
  clip_metadata?: { clips: Clip[] };
  created_at: string;
  updated_at: string;
}

function formatTimecode(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export default function JobPage() {
  const params = useParams();
  const jobId = params.job_id as string;
  const [job, setJob] = useState<Job | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/jobs/${jobId}`
        );
        if (!res.ok) throw new Error("Job not found");
        const data = await res.json();
        if (!cancelled) {
          setJob(data);
          setFetchError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setFetchError(err instanceof Error ? err.message : "Failed to load job");
        }
      }
    }

    poll();
    const interval = setInterval(() => {
      if (job?.status !== "COMPLETED" && job?.status !== "FAILED") {
        poll();
      }
    }, 3000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };

  }, [jobId, job?.status]);

  const currentStageIndex = job ? STAGES.indexOf(job.status) : -1;
  const isFailed = job?.status === "FAILED";
  const isCompleted = job?.status === "COMPLETED";

  return (
    <main className="min-h-screen bg-[#0B0D0F] text-[#EDEAE3] px-6 py-16">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center gap-2 mb-8 font-mono text-xs tracking-[0.2em] text-[#8A857A]">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              isFailed
                ? "bg-[#FF3B30]"
                : isCompleted
                ? "bg-[#4ADE80]"
                : "bg-[#FF3B30] animate-pulse"
            }`}
          />
          <span>DECK 01 — JOB {jobId.slice(0, 8)}</span>
        </div>

        {fetchError && (
          <p className="font-mono text-sm text-[#FF3B30]">{fetchError}</p>
        )}

        {!job && !fetchError && (
          <p className="font-mono text-sm text-[#8A857A]">Reading tape...</p>
        )}

        {job && (
          <>
            {/* Reel / stage tracker */}
            {!isFailed && (
              <div className="mb-12">
                <div className="flex justify-between mb-3">
                  {STAGES.map((stage, i) => (
                    <div
                      key={stage}
                      className="flex flex-col items-center gap-2 flex-1"
                    >
                      <span
                        className={`w-2.5 h-2.5 rounded-full transition-colors ${
                            i < currentStageIndex || isCompleted
                            ? "bg-[#4ADE80]"
                            : i === currentStageIndex
                            ? "bg-[#FF3B30] animate-pulse"
                            : "bg-[#2A2D31]"
                        }`}
                        />
                    </div>
                  ))}
                </div>
                <div className="h-px bg-[#1C1E22] relative">
                  <div
                    className="absolute top-0 left-0 h-px bg-[#4ADE80] transition-all duration-500"
                    style={{
                      width: `${
                        currentStageIndex <= 0
                          ? 0
                          : (currentStageIndex / (STAGES.length - 1)) * 100
                      }%`,
                    }}
                  />
                </div>
                <p className="mt-4 font-mono text-sm text-[#EDEAE3]">
                  {STAGE_LABELS[job.status] || job.status}
                </p>
              </div>
            )}

            {isFailed && (
              <div className="mb-12 border border-[#FF3B30] px-5 py-4">
                <p className="font-mono text-xs tracking-widest text-[#FF3B30] mb-2">
                  ERR
                </p>
                <p className="text-sm text-[#EDEAE3]">
                  {job.error_message || "Something went wrong processing this tape."}
                </p>
              </div>
            )}

            {/* Completed clips */}
            {isCompleted && job.clip_metadata?.clips && (
              <div className="space-y-6">
                <h2 className="text-2xl font-medium tracking-tight mb-2">
                  {job.clip_metadata.clips.length} clip
                  {job.clip_metadata.clips.length !== 1 ? "s" : ""} ready
                </h2>

                {job.clip_metadata.clips.map((clip, i) => (
                  <div
                    key={i}
                    className="border border-[#2A2D31] bg-[#111316] p-5"
                  >
                    <div className="flex justify-between items-start mb-3">
                      <div>
                        <p className="font-medium">{clip.title}</p>
                        {clip.reason && (
                          <p className="text-sm text-[#8A857A] mt-1">
                            {clip.reason}
                          </p>
                        )}
                      </div>
                      <span className="font-mono text-xs text-[#4A4D51] whitespace-nowrap ml-4">
                        {formatTimecode(clip.start_time)} –{" "}
                        {formatTimecode(clip.end_time)}
                      </span>
                    </div>

                    <video
                      src={clip.url}
                      controls
                      className="w-full bg-black mb-3"
                    />

                    <a
                      href={clip.url}
                      download={clip.filename}
                      className="inline-block px-4 py-2 bg-[#EDEAE3] text-[#0B0D0F] text-sm font-medium hover:bg-white transition-colors"
                    >
                      Download clip
                    </a>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </main>
  );
}