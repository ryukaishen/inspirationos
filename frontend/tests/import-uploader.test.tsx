import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImportUploader } from "@/components/import-uploader";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof api>();
  return { ...original, uploadImportZip: vi.fn() };
});

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

const mockedUpload = vi.mocked(api.uploadImportZip);

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function makeZipFile(name = "export.zip"): File {
  return new File([new Uint8Array([0x50, 0x4b, 0x05, 0x06])], name, {
    type: "application/zip",
  });
}

async function chooseFileAndUpload(): Promise<void> {
  await userEvent.upload(screen.getByLabelText("Export ZIP file"), makeZipFile());
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
}

describe("ImportUploader", () => {
  beforeEach(() => {
    mockedUpload.mockReset();
    pushMock.mockReset();
  });

  it("uploads the chosen file and navigates to the new import", async () => {
    mockedUpload.mockResolvedValue({ import_id: 7, job_id: 9 });

    renderWithClient(<ImportUploader />);
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
    await chooseFileAndUpload();

    expect(mockedUpload).toHaveBeenCalledTimes(1);
    expect(mockedUpload.mock.calls[0][0].name).toBe("export.zip");
    expect(pushMock).toHaveBeenCalledWith("/import/7");
  });

  it("shows the actionable HTML-export rejection message", async () => {
    const message =
      "This export is in HTML format, which cannot be parsed. " +
      "Re-request your Instagram data export in JSON format, then upload the new ZIP.";
    mockedUpload.mockRejectedValue(new ApiError(400, "html_export", message));

    renderWithClient(<ImportUploader />);
    await chooseFileAndUpload();

    expect(await screen.findByTestId("upload-error")).toHaveTextContent(message);
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("shows a duplicate notice linking to the existing import", async () => {
    mockedUpload.mockRejectedValue(
      new ApiError(409, "duplicate", "this ZIP was already uploaded (matching checksum)", 3),
    );

    renderWithClient(<ImportUploader />);
    await chooseFileAndUpload();

    expect(await screen.findByTestId("upload-error")).toHaveTextContent("already uploaded");
    const link = screen.getByRole("link", { name: "View the existing import" });
    expect(link).toHaveAttribute("href", "/import/3");
  });
});
