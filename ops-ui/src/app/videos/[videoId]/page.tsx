import { redirect } from "next/navigation";

export default async function LegacyVideoPage({ params }: { params: Promise<{ videoId: string }> }) {
  const { videoId } = await params;
  redirect(`/content/videos/${videoId}`);
}
