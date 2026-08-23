#!/usr/bin/env bash
# vram_sampler.sh — log total GPU memory used every 2s to /root/vram.log.
# Usage: scripts/vram_sampler.sh start|stop|report
set -u
LOG=/root/vram.log
case "${1:-report}" in
  run)
    # foreground loop — wrap in a persistent harness background job
    rm -f "$LOG"
    while true; do
      nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits >> "$LOG"
      sleep 2
    done
    ;;
  start)
    rm -f "$LOG"
    setsid nohup bash -c 'while true; do nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits >> /root/vram.log; sleep 2; done' \
      >/dev/null 2>&1 &
    echo "sampler started"
    ;;
  stop)
    pkill -f "vram.log" 2>/dev/null
    echo "sampler stopped"
    ;;
  report)
    if [[ -f "$LOG" ]]; then
      echo "samples=$(wc -l < "$LOG") max_mib=$(sort -n "$LOG" | tail -1) last_mib=$(tail -1 "$LOG")"
    else
      echo "no samples"
    fi
    ;;
esac
