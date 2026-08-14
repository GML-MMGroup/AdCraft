export type VideoDimensions = {
  width: number;
  height: number;
};

export type StageDimensions = {
  width: number;
  height: number;
};

export function fitVideoDimensionsWithinStage(
  video: VideoDimensions,
  stage: StageDimensions,
): VideoDimensions | null {
  if (video.width <= 0 || video.height <= 0 || stage.width <= 0 || stage.height <= 0) {
    return null;
  }
  const scale = Math.min(stage.width / video.width, stage.height / video.height);
  return {
    width: Math.round(video.width * scale),
    height: Math.round(video.height * scale),
  };
}
