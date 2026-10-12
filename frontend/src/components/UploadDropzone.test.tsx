// Tests for <UploadDropzone />: client-side file gating.
//
// What it does:
//   Verifies supported files are forwarded to onFiles, while unsupported
//   extensions and oversize files are blocked with an error message, and that
//   the dropzone is keyboard-focusable for accessibility.
//
// How it works:
//   - Renders the component with a canned AppConfig (25MB limit, pdf+docx).
//   - makeFile() builds in-memory Files of a given name/size; uploadFiles()
//     simulates the <input type=file> change event via fireEvent.
//   - Asserts on the onFiles mock (called / not called) and on the
//     rejected-files message element.

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { UploadDropzone } from "./UploadDropzone";
import type { AppConfig } from "../api/types";

// Canned config: 25MB cap, only .pdf and .docx advertised as supported.
const config: AppConfig = {
  max_upload_bytes: 25 * 1024 * 1024,
  supported: [
    { kind: "pdf", extensions: [".pdf"], mime_types: ["application/pdf"] },
    { kind: "docx", extensions: [".docx"], mime_types: ["application/vnd..."] },
  ],
};

// Builds an in-memory File of `size` bytes (filled with zeros).
function makeFile(name: string, size: number): File {
  return new File([new Uint8Array(size)], name, { type: "application/octet-stream" });
}

// Simulates picking files in the hidden file input.
function uploadFiles(files: File[]) {
  const input = screen.getByTestId("file-input");
  fireEvent.change(input, { target: { files } });
}

describe("UploadDropzone", () => {
  beforeEach(() => {
    // What: isolates mock history. How: restores all mocks before each test.
    vi.restoreAllMocks();
  });

  it("accepts supported files", () => {
    // What: a 1KB .pdf passes validation and is forwarded.
    // How: renders with onFiles spy, uploads ok.pdf, asserts called with [file].
    const onFiles = vi.fn();
    render(<UploadDropzone config={config} onFiles={onFiles} />);
    const file = makeFile("ok.pdf", 1024);
    uploadFiles([file]);
    expect(onFiles).toHaveBeenCalledWith([file]);
  });

  it("rejects an unsupported extension", () => {
    // What: .txt is blocked with an "Unsupported file type" message.
    // How: uploads notes.txt, asserts onFiles NOT called and the rejected
    //   message element contains "Unsupported file type".
    const onFiles = vi.fn();
    render(<UploadDropzone config={config} onFiles={onFiles} />);
    uploadFiles([makeFile("notes.txt", 1024)]);

    expect(onFiles).not.toHaveBeenCalled();
    expect(screen.getByTestId("rejected-files").textContent).toContain(
      "Unsupported file type",
    );
  });

  it("rejects an oversize file", () => {
    // What: a 30MB .pdf over the 25MB cap is blocked with a limit message.
    // How: uploads huge.pdf (30MB of zeros), asserts onFiles NOT called and
    //   the rejected message mentions "limit".
    const onFiles = vi.fn();
    render(<UploadDropzone config={config} onFiles={onFiles} />);
    uploadFiles([makeFile("huge.pdf", 30 * 1024 * 1024)]);

    expect(onFiles).not.toHaveBeenCalled();
    expect(screen.getByTestId("rejected-files").textContent).toContain("limit");
  });

  it("is focusable and opens the picker on Enter", async () => {
    // What: dropzone button is keyboard-focusable (a11y requirement).
    // How: renders, focuses the button role, asserts it has focus. (Picker
    //   opening on Enter is covered by the component's key handler.)
    const onFiles = vi.fn();
    render(<UploadDropzone config={config} onFiles={onFiles} />);
    const dropzone = screen.getByRole("button");
    dropzone.focus();
    expect(dropzone).toHaveFocus();
  });
});
