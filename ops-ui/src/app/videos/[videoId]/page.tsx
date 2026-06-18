import { notFound } from "next/navigation";
import { VideoDetailPage } from "@/components/pages/video-detail-page";

export default async function Page({
  params,
}: {
  params: Promise<{ videoId: string }>;
}) {
  const { videoId } = await params;
  const parsedVideoId = Number(videoId);
  if (!Number.isInteger(parsedVideoId) || parsedVideoId < 1) {
    notFound();
  }
  return <VideoDetailPage videoId={parsedVideoId} />;
}
