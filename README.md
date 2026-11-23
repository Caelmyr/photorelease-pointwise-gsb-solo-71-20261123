# PhotoRelease

PhotoRelease is a local workbench for preparing photographs for publication. Add originals or finished photographs, mark regions, review the encoded public preview, and retain each issued delivery separately from the draft.

## Start

Use `docker compose up --build --wait` and open http://127.0.0.1:19994. Set `PHOTORELEASE_PORT` to select another port. Stop with `docker compose stop`. The named volume stores desks, photographs, and issues. For a native installation, use Python 3.11 or 3.12, install `requirements.txt`, then run `./start.sh`. The native default is http://127.0.0.1:8000 and the local data folder is `.photorelease/`.

## Prepare an issue

1. Open **Load sample desk** for three synthetic workshop images, or create an empty desk and upload your own. **Image preparation** provides the separate capture, comparison, alignment, corrections and finishing workbench from the local image engine. **Add from preparation** takes an editable asset or a particular finished result into the current desk as a separate photo.
2. On **Source**, draw a crop and mark rectangles for coverage or editorial retention. Change a rectangle with its **Edit** button. The mark list gives the portion of the rectangle inside the current crop. Keep marks guide review. Select your output size, PNG or JPEG, cover color, and an optional public caption.
3. Check **Public preview** and approve it for the issue. A crop, mark or output change requires another approval. Exclude photos you do not intend to share and set the remaining order. Use **Contact sheet** to check that order before creating an issue.
4. For same-position bursts, open **Burst review**: pick 2–12 same-size photographs, circle a watch region (for example hands on a repair bench, or reuse an existing mark), and compare two rules — every member resembles the representative you keep, or every pair inside a group resembles each other. Move the similarity slider to re-partition instantly; each group names its most different pair and offers a three-panel view (kept photo, aligned other photo, highlighted changes with the worst 1-of-24 comparison block outlined). Choose the representative per group, then apply: only this draft's non-representative photos are unchecked and annotated with the photo that represents them, visible in the photo list and the inspector. **Applied grouping history** records every plan; saved issues are never modified.
5. Use **Create issue** to store and download the public photos with contact sheets and a file integrity manifest. Use **Issue history** to reopen or download the original saved bytes and compare two same-size saved versions of a selected photo. **Verify a ZIP** checks declared files against the included integrity manifest.

Use a single-frame PNG, JPEG, WebP or TIFF with 32–4,096 pixels per side, up to 12 megapixels and 24 MB. Desks allow up to 24 photos, 40 marks per photo and 24 saved issues. Public images are fresh RGB encodings with a maximum long edge of 1,600 pixels. Issue files are capped to fit the 96 MB verification budget. The built-in sample is an illustration of a fictional workshop.

Coverage is applied to normalized source pixels before crop scaling. Only manually drawn cover regions are processed. Check what remains in the whole preview and what you enter in public captions. Originals and the preparation tools are available in the local editor. Give recipients the downloaded issue ZIP from the approved draft. The ZIP integrity checker uses checksums and does not authenticate an issuer.
