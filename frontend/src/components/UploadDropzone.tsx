import { useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import type { AppConfig } from "../api/types";

interface Rejected {
  name: string;
  size: number;
  reason: string;
}

export function UploadDropzone({
  config,
  onFiles,
}: {
  config?: AppConfig;
  onFiles: (files: File[]) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [rejected, setRejected] = useState<Rejected[]>([]);

  const acceptedExtensions = config?.supported.flatMap((s) => s.extensions) ?? [];
  const maxBytes = config?.max_upload_bytes ?? Infinity;

  const validate = (files: File[]): { accepted: File[]; rejected: Rejected[] } => {
    const accepted: File[] = [];
    const bad: Rejected[] = [];
    for (const file of files) {
      const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
      if (acceptedExtensions.length > 0 && !acceptedExtensions.includes(ext)) {
        bad.push({ name: file.name, size: file.size, reason: `Unsupported file type (${ext || "no extension"}).` });
        continue;
      }
      if (file.size === 0) {
        bad.push({ name: file.name, size: file.size, reason: "File is empty." });
        continue;
      }
      if (file.size > maxBytes) {
        bad.push({
          name: file.name,
          size: file.size,
          reason: `Exceeds the ${(maxBytes / 1024 / 1024).toFixed(0)} MB limit.`,
        });
        continue;
      }
      accepted.push(file);
    }
    return { accepted, rejected: bad };
  };

  const handleFiles = (files: File[]) => {
    if (files.length === 0) return;
    const { accepted, rejected: bad } = validate(files);
    setRejected(bad);
    if (accepted.length > 0) onFiles(accepted);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    handleFiles(Array.from(e.dataTransfer.files));
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      inputRef.current?.click();
    }
  };

  return (
    <div className="upload">
      <div
        className={`dropzone${dragging ? " dropzone--dragging" : ""}`}
        role="button"
        tabIndex={0}
        aria-label="Upload documents. Drag and drop files, or press Enter to browse."
        onClick={() => inputRef.current?.click()}
        onKeyDown={onKeyDown}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <p className="dropzone__title">Drop files here or click to browse</p>
        <p className="dropzone__hint">
          {config
            ? `Accepted: ${acceptedExtensions.join(", ")} · max ${(maxBytes / 1024 / 1024).toFixed(0)} MB`
            : "Loading accepted formats…"}
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={acceptedExtensions.join(",")}
          data-testid="file-input"
          style={{ display: "none" }}
          onChange={(e) => {
            handleFiles(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
      </div>
      {rejected.length > 0 && (
        <ul className="upload__rejected" data-testid="rejected-files">
          {rejected.map((r, i) => (
            <li key={i}>
              <strong>{r.name}</strong> — {r.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}