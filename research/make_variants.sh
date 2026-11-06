#!/bin/sh
# Twitch-like degradations of the HD recordings: upscale to 1080p, re-encode at a streaming bitrate.
# usage: research/make_variants.sh <input.mp4> <outprefix>
in="$1"; out="$2"
for br in 6000 2500; do
  ffmpeg -y -v error -i "$in" -an -vf "scale=1920:1080:flags=lanczos,fps=30" -c:v libx264 -preset veryfast -b:v ${br}k -maxrate ${br}k -bufsize $((br*2))k -pix_fmt yuv420p "${out}_tw${br}.mp4"
done
