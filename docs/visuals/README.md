# EIDOLON visuals

Dark, modern diagrams for the white paper and social posts. Each is authored as
an editable **SVG** and rendered to a high-res **PNG** (via
[`@resvg/resvg-js-cli`](https://github.com/yisibl/resvg-js)).

| Asset | Use |
|---|---|
| `architecture.png` / `.svg` | Hero architecture diagram (whole system) |
| `decision-gate.png` / `.svg` | The KAIROS gate — locked order + five outcomes |
| `gateway.png` / `.svg` | The authority layer — governing MCP gateway |
| `carousel/slide-1..6.png` | LinkedIn carousel (square 1080×1080) |
| `carousel/eidolon-carousel.pdf` | The 6 slides as one PDF — upload as a LinkedIn *document* |

## Regenerate the PNGs

```bash
# landscape diagrams
for f in architecture decision-gate gateway; do
  npx -y @resvg/resvg-js-cli --fit-width 2560 "$f.svg" "$f.png"
done
# carousel
for i in 1 2 3 4 5 6; do
  npx -y @resvg/resvg-js-cli --fit-width 1080 "carousel/slide-$i.svg" "carousel/slide-$i.png"
done
# carousel PDF (needs Pillow)
python -c "from PIL import Image; im=[Image.open(f'carousel/slide-{i}.png').convert('RGB') for i in range(1,7)]; im[0].save('carousel/eidolon-carousel.pdf', save_all=True, append_images=im[1:], resolution=144)"
```

Colors match the web dashboard (bg `#0b0e14`, accent `#7c7bff`, green `#39d98a`,
amber `#f2b84b`, red `#ff6b6b`, cyan `#5cc8ff`). Edit the SVGs and re-render.
