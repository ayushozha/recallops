#!/bin/bash
set -e
rm -f list.txt sclip*.mp4
TEMPO=1.2
dur(){ ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }
# image | audio | crop (w:h:x:y or full) | audio part (all|first|second)
SCENES=(
"slide_intro.png|st01.mp3|full|all"
"slide_solution.png|st02.mp3|full|all"
"slide_solution.png|st03.mp3|1440:810:40:170|all"
"app_map.png|st04.mp3|full|all"
"slide_solution.png|st05.mp3|1280:720:640:150|all"
"app_notice.png|st06.mp3|full|all"
"app_graph_before.png|st07.mp3|1500:844:300:330|all"
"app_orders.png|st08.mp3|full|first"
"app_graph_after.png|st08.mp3|1500:844:300:330|second"
"proof.png|st09.mp3|full|all"
"slide_outcome.png|st10.mp3|full|all"
"slide_intro.png|st11.mp3|full|all"
)
n=0
for s in "${SCENES[@]}"; do
  IFS='|' read -r img aud crop part <<< "$s"; n=$((n+1))
  full=$(dur $aud); spoken=$(python3 -c "print($full/$TEMPO)")
  case $part in
    all) ss=0; d=$(python3 -c "print(round($spoken+0.2,2))");;
    first) ss=0; d=$(python3 -c "print(round($spoken*0.5,2))");;
    second) ss=$(python3 -c "print(round($full*0.5,2))"); d=$(python3 -c "print(round($spoken*0.5+0.2,2))");;
  esac
  if [ "$crop" = "full" ]; then pre="scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0xFAF8F4"; else pre="crop=$crop"; fi
  fo=$(python3 -c "print(round($d-0.25,2))")
  ffmpeg -v error -y -loop 1 -framerate 30 -t $d -i $img -ss $ss -i $aud -filter_complex \
   "[0:v]$pre,scale=2040:1148,crop=1920:1080:x='(iw-ow)*t/$d':y='(ih-oh)/2',fade=t=in:st=0:d=0.25,fade=t=out:st=$fo:d=0.25,format=yuv420p[v];[1:a]atempo=$TEMPO,apad,atrim=0:$d,aresample=48000[a]" \
   -map "[v]" -map "[a]" -t $d -c:v libx264 -preset veryfast -crf 19 -r 30 -c:a aac -b:a 160k sclip$n.mp4
  echo "file 'sclip$n.mp4'" >> list.txt; echo "scene $n $img $crop $d"
done
ffmpeg -v error -y -f concat -safe 0 -i list.txt -c copy RecallOps-demo.mp4
dur RecallOps-demo.mp4
