// React hooks and event types for the dropzone.
import { useRef, useState, type DragEvent, type KeyboardEvent } from "react";
// AppConfig type describing supported formats and limits.
import type { AppConfig } from "../api/types";

// Describes a file that failed validation.
interface Rejected {
  name: string;
  size: number;
  reason: string;
}

// Drag-and-drop / click file upload area with client-side validation.
export function UploadDropzone({
  config,
  onFiles,
}: {
  config?: AppConfig;
  onFiles: (files: File[]) => void;
}) {
  // Ref to the hidden file input so it can be clicked programmatically.
  const inputRef = useRef<HTMLInputElement>(null);
  // Whether a drag is currently hovering the dropzone.
  const [dragging, setDragging] = useState(false);
  // Files that failed validation, shown to the user.
  const [rejected, setRejected] = useState<Rejected[]>([]);

  // Flatten all supported extensions from the server config.
  const acceptedExtensions = config?.supported.flatMap((s) => s.extensions) ?? [];
  // Maximum allowed file size in bytes, unbounded when config is absent.
  const maxBytes = config?.max_upload_bytes ?? Infinity;

  // Split a list of files into accepted and rejected lists.
  const validate = (files: File[]): { accepted: File[]; rejected: Rejected[] } => {
    // Files that passed validation.
    const accepted: File[] = [];
    // Files that failed validation with reasons.
    const bad: Rejected[] = [];
    // Evaluate each file against the extension, emptiness, and size rules.
    for (const file of files) {
      // Lowercased file extension including the leading dot.
      const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
      // Reject files whose extension is not in the supported list.
      if (acceptedExtensions.length > 0 && !acceptedExtensions.includes(ext)) {
        bad.push({ name: file.name, size: file.size, reason: `Unsupported file type (${ext || "no extension"}).` });
        continue;
      }
      // Reject zero-byte files.
      if (file.size === 0) {
        bad.push({ name: file.name, size: file.size, reason: "File is empty." });
        continue;
      }
      // Reject files larger than the configured maximum.
      if (file.size > maxBytes) {
        bad.push({
          name: file.name,
          size: file.size,
          reason: `Exceeds the ${(maxBytes / 1024 / 1024).toFixed(0)} MB limit.`,
        });
        continue;
      }
      // Otherwise accept the file.
      accepted.push(file);
    }
    return { accepted, rejected: bad };
  };

  // Validate files and forward accepted ones to the parent.
  const handleFiles = (files: File[]) => {
    // Ignore empty selections.
    if (files.length === 0) return;
    // Partition the files by validity.
    const { accepted, rejected: bad } = validate(files);
    // Surface rejected files to the user.
    setRejected(bad);
    // Only notify the parent when something was accepted.
    if (accepted.length > 0) onFiles(accepted);
  };

  // Handle a drop event on the dropzone.
  const onDrop = (e: DragEvent) => {
    // Prevent the browser from opening the dropped file.
    e.preventDefault();
    // Clear the dragging highlight.
    setDragging(false);
    // Process the dropped files.
    handleFiles(Array.from(e.dataTransfer.files));
  };

  // Open the file picker when activated via keyboard.
  const onKeyDown = (e: KeyboardEvent) => {
    // Treat Enter and Space as activation of the dropzone button.
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
          // Allow dropping by preventing the default browser behavior.
          e.preventDefault();
          // Highlight the dropzone while dragging over it.
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <p className="dropzone__title">Drop files here or click to browse</p>
        <p className="dropzone__hint">
          {/* Show accepted formats/size limit, or a loading hint before config arrives. */}
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
            // Process files chosen through the file picker.
            handleFiles(Array.from(e.target.files ?? []));
            // Reset the input so the same file can be chosen again.
            e.target.value = "";
          }}
        />
      </div>
      {/* List rejected files and their reasons when any exist. */}
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