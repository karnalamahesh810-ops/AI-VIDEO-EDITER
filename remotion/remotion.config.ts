import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setConcurrency(4);
// public dir (runtime: holds broll/ clips, narration.mp3, scenes.json) is passed
// per-command via --public-dir so the same project works locally and on Lambda.
