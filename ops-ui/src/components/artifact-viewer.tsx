import { JsonInspector } from "@/components/json-inspector";

export default function ArtifactViewer({ value }: { value: unknown }) {
  return <div data-slot="artifact-viewer" className="min-w-0"><JsonInspector value={value} empty="생성된 아티팩트가 없습니다." /></div>;
}
