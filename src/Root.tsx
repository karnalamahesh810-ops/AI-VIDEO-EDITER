import React from "react";
import { Composition } from "remotion";
import { ArticleZoom } from "./compositions/ArticleZoom";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="ArticleZoom"
        component={ArticleZoom}
        durationInFrames={150}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};
