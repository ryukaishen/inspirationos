import { ImportList } from "@/components/import-list";
import { ImportUploader } from "@/components/import-uploader";

export default function ImportPage() {
  return (
    <main className="mx-auto w-full max-w-2xl flex-1 space-y-6 px-6 py-12">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Import</h1>
        <p className="text-sm text-muted-foreground">
          Upload your Instagram export ZIP and follow the scan.
        </p>
      </div>
      <ImportUploader />
      <ImportList />
    </main>
  );
}
