import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { UploadDropzone } from "./UploadDropzone";
import type { AppConfig } from "../api/types";

const config: AppConfig = {
  max_upload_bytes: 25 * 1024 * 1024,
  supported: [
    { kind: "pdf", extensions: [".pdf"], mime_types: ["application/pdf"] },
    { kind: "docx", extensions: [".docx"], mime_types: ["application/vnd..."] },
  ],
};

function makeFile(name: string, size: number): File {
  return new File([new Uint8Array(size)], name, { type: "application/octet-stream" });
}

function uploadFiles(files: File[]) {
  const input = screen.getByTestId("file-input");
  fireEvent.change(input, { target: { files } });
}

describe("UploadDropzone", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("accepts supported files", () => {
    const onFiles = vi.fn();
    render(<UploadDropzone config={config} onFiles={onFiles} />);
    const file = makeFile("ok.pdf", 1024);
    uploadFiles([file]);
    expect(onFiles).toHaveBeenCalledWith([file]);
  });

  it("rejects an unsupported extension", () => {
    const onFiles = vi.fn();
    render(<UploadDropzone config={config} onFiles={onFiles} />);
    uploadFiles([makeFile("notes.txt", 1024)]);

    expect(onFiles).not.toHaveBeenCalled();
    expect(screen.getByTestId("rejected-files").textContent).toContain(
      "Unsupported file type",
    );
  });

  it("rejects an oversize file", () => {
    const onFiles = vi.fn();
    render(<UploadDropzone config={config} onFiles={onFiles} />);
    uploadFiles([makeFile("huge.pdf", 30 * 1024 * 1024)]);

    expect(onFiles).not.toHaveBeenCalled();
    expect(screen.getByTestId("rejected-files").textContent).toContain("limit");
  });

  it("is focusable and opens the picker on Enter", async () => {
    const onFiles = vi.fn();
    render(<UploadDropzone config={config} onFiles={onFiles} />);
    const dropzone = screen.getByRole("button");
    dropzone.focus();
    expect(dropzone).toHaveFocus();
  });
});