# Model licenses: open points

Status: 2026-10-29. Not legal advice. We take care of these points later, before the backend is
handed to someone else or before real operation with authorities.

Related files:
- [documentation.md](documentation.md), section 12: the full license review with the tables.
- [../backend/MODEL_NOTICES.md](../backend/MODEL_NOTICES.md): source, license, copyright and citation of each model. It is part of the Docker image.
- [../backend/assets/LICENSE-yunet.txt](../backend/assets/LICENSE-yunet.txt): MIT license text of YuNet.

**Hosting is not distributing.** As long as we only run the backend ourselves, the duties below
(license texts, source offers) are not triggered. They start when the backend is delivered to a third
party, for example an authority that hosts it itself.

## Overview

| Model | Purpose | License | State today |
|---|---|---|---|
| GLiNER2-PII (`fastino/gliner2-privacy-filter-PII-multi`) | personal data in text | Apache 2.0 | notices written, provenance of the training data open |
| YuNet (`face_detection_yunet_2023mar.onnx`) | faces in photos | MIT | notices and license text in the repo, training data open |
| PP-OCRv6 small and `ch_ppocr_mobile_v2.0_cls` via RapidOCR | text in photos | Apache 2.0 | notices written, no open point |

## Per model

### GLiNER2-PII

- [ ] Ask a person with legal expertise whether the training data is a problem. The model was trained
      on 4,910 synthetic texts generated with GPT-5.4 (no human review). The model card does not address
      the terms of use of the generator, for example a clause against using outputs to build competing models.
- [ ] Check the license of the base weights of GLiNER2. The repository page names Apache 2.0 for the code, not for the weights.
- [ ] Check the license of the encoder (DeBERTa-v3 / mDeBERTa-v3). We believe it is MIT, not verified.
- [ ] Before a delivery: include the Apache 2.0 license text and the notices with the image.
- Fallback if it cannot be cleared: `urchade/gliner_multi_pii-v1` (Apache 2.0, our first candidate, older and with a lower recall, its own training data has to be checked too) or the OpenAI Privacy Filter (open weights, Apache 2.0, text only, language coverage not checked).

### YuNet

- [ ] Check the training data. The model README does not name it. The performance is measured on WIDER FACE,
      whose dataset is listed as CC BY-NC-ND 4.0 on Hugging Face (other sources: academic use only). Whether weights
      trained on it count as a derivative is an unsettled legal question.
- [ ] Ask the authors (libfacedetection.train, Shiqi Yu) which data the model was trained on and under which terms.
- [ ] Before a delivery: keep `assets/LICENSE-yunet.txt` and the copyright notice with the model file.
- Fallback if it cannot be cleared: MediaPipe BlazeFace (Apache 2.0, made for close frontal faces, lower recall for faces far away)
  or EgoBlur (Apache 2.0 according to its README, two models of about 400 MB each, weights only after an email form and a license
  agreement aimed at researchers, not tested by us).

### PP-OCRv6 small (RapidOCR)

- No open point. The license file `MODEL_LICENSES.md` inside the `rapidocr` package states Apache 2.0, copyright of the weights with
  Baidu and the PaddleOCR rights holders, no non-commercial restriction found.
- [ ] Before a delivery: include the Apache 2.0 license text and the notices with the image.

## Checklists

**Before the backend is delivered to a third party**
- [ ] Run `make notices` in `backend/` before `docker build` (the list of all libraries with their license texts goes into the image).
- [ ] Include the Apache 2.0 license text for GLiNER2-PII and the OCR models.
- [ ] Remove `libx265` from the image (the HEIC library `pillow-heif` bundles it, it is GPL-2.0). Either build libheif without it or let the connector reject HEIC.
- [ ] Do not ship the local S3 (MinIO, AGPL-3.0, archived).
- [ ] Offer the source of the LGPL parts (psycopg, libheif, libde265, FFmpeg parts of OpenCV) or point to their upstream sources.

**Before real operation with authorities**
- [ ] Legal view on the training data of YuNet and of GLiNER2-PII (see above), or switch to models with clear terms.
- [ ] Check HEVC patent questions for HEIC decoding (only relevant if HEIC stays on the server).
