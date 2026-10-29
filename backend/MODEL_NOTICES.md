# Model notices

The privacy layer uses three third-party models. None of them was modified by us. This file
travels with the backend (it is part of the Docker image) so the license duties of the models
are met if the image is ever handed to someone else. See docs/documentation.md, section 12, for
the review and the open points.

## GLiNER2-PII (text: names, emails, phone numbers, IBAN, plates)

- Model: `fastino/gliner2-privacy-filter-PII-multi`, https://huggingface.co/fastino/gliner2-privacy-filter-PII-multi
- Publisher: Fastino (the Fastino AI Team)
- License: Apache License 2.0 (as stated on the model card), https://www.apache.org/licenses/LICENSE-2.0
- Based on GLiNER2 (code Apache 2.0), https://github.com/fastino-ai/GLiNER2
- Where it lives: downloaded into the image at build time (`HF_HOME=/opt/hf`), unmodified.
- Citation: GLiNER2-PII: A Multilingual Model for Personally Identifiable Information Extraction,
  https://arxiv.org/abs/2605.09973
- Open: the model was trained on synthetic data generated with GPT-5.4, the card does not address
  the terms of use of that generator.

## YuNet (images: faces)

- Model: `face_detection_yunet_2023mar.onnx` from the OpenCV Zoo,
  https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
- License: MIT, Copyright (c) 2020 Shiqi Yu. The full text is in `assets/LICENSE-yunet.txt`
  and has to be kept with the model file.
- Origin: libfacedetection.train, https://github.com/ShiqiYu/libfacedetection
- Where it lives: `assets/face_detection_yunet_2023mar.onnx` in the repository, unmodified.
- Citation: Wu, W., Peng, H., Yu, S. (2023). YuNet: A tiny millisecond-level face detector.
  Machine Intelligence Research, 20(5), 656-665.
- Open: the training data is not named in the model README. The accuracy is measured on
  WIDER FACE, whose dataset is listed as CC BY-NC-ND 4.0.

## PP-OCRv6 small (images: text recognition) via RapidOCR

- Models: `PP-OCRv6_det_small.onnx`, `PP-OCRv6_rec_small.onnx`, `ch_ppocr_mobile_v2.0_cls_mobile.onnx`
- Distributed by: RapidOCR, https://github.com/RapidAI/RapidOCR (code Apache 2.0)
- Origin and copyright of the weights: Baidu and the PaddleOCR rights holders,
  https://github.com/PaddlePaddle/PaddleOCR (Apache 2.0)
- License: Apache License 2.0. The statement of RapidOCR is in its package file
  `MODEL_LICENSES.md` (inside the installed `rapidocr` package), no non-commercial restriction found.
- Where they live: inside the `rapidocr` Python package, unmodified.
