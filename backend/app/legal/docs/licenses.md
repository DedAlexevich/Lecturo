# Лицензии сторонних компонентов

Редакция от 2026-10-27

Все реквизиты и данные в документе тестовые. Lecturo — учебный проект и пока не ведёт коммерческую деятельность.

## 1. Термины и определения

1.1. В настоящем документе используются следующие термины и определения:

1.1.1. **Документ** — настоящие сведения о лицензиях сторонних компонентов.

1.1.2. **Администрация** — Иванов Иван Иванович, физическое лицо, применяющее специальный налоговый режим «Налог на профессиональный доход», ИНН 770123456703, владелец Сервиса.

1.1.3. **Сервис** — сайт lecturo.ru, его версия в мессенджере Telegram (Telegram Mini App), устанавливаемое веб-приложение (PWA) и Telegram-бот Lecturo.

1.1.4. **Пользователь** — физическое лицо, использующее Сервис.

1.1.5. **Пользовательское соглашение** — [Пользовательское соглашение](/legal/terms) Сервиса.

1.1.6. **Локальный режим** — обработка Материалов на устройстве Пользователя в браузере без передачи Материалов на серверы Сервиса.

1.1.7. **Компонент** — программа для ЭВМ, библиотека, шрифт, модель распознавания речи или языковая модель, исключительное право на которые принадлежит третьему лицу и которые передаются в браузер Пользователя при работе Сервиса.

1.1.8. **Открытая лицензия** — лицензионный договор, условия которого доступны неопределённому кругу лиц и по которому правообладатель предоставляет право использования Компонента (статья 1286.1 ГК РФ).

1.1.9. **Исходный код** — форма Компонента, предназначенная для его изучения и изменения, включая сценарии сборки.

1.1.10. **Ядро ffmpeg.wasm** — сборка программы FFmpeg в формате WebAssembly, распространяемая в пакете `@ffmpeg/core` и используемая в Локальном режиме для извлечения звука из видеозаписи.

1.2. Термин «Материалы», а также иные термины, не определённые в Документе, используются в значении, установленном Пользовательским соглашением.

## 2. Общие положения

2.1. Документ содержит перечень Компонентов, их версии, условия Открытых лицензий, сведения о правообладателях и о месте получения Исходного кода.

2.2. Администрация использует Компоненты на условиях Открытых лицензий, указанных в разделе 3 Документа. Пользователь вправе использовать каждый Компонент, полученный в составе Сервиса, на условиях его Открытой лицензии.

2.3. Исключительные права на Компоненты принадлежат их правообладателям. Документ не изменяет условия Открытых лицензий. При расхождении сведений Документа с текстом Открытой лицензии применяется текст Открытой лицензии.

2.4. Отказ правообладателей от гарантий и ограничение их ответственности, предусмотренные Открытыми лицензиями, относятся к правообладателям и не ограничивают обязанности Администрации перед Пользователем, установленные Пользовательским соглашением и законодательством Российской Федерации.

2.5. Документ не распространяется на собственный программный код Сервиса, условия распространения которого установлены пунктом 3.5 Пользовательского соглашения, а также на программы, используемые только при разработке и сборке Сервиса и не передаваемые Пользователю.

## 3. Перечень Компонентов

3.1. В браузер Пользователя при открытии Сервиса передаются следующие Компоненты:

3.1.1. **React** и **React DOM** версии 18.3.1, **Scheduler** версии 0.23.2 — библиотеки построения интерфейса.

- Открытая лицензия: MIT.
- Правообладатель: `Copyright (c) Facebook, Inc. and its affiliates.`
- Исходный код: [github.com/facebook/react, тег v18.3.1](https://github.com/facebook/react/tree/v18.3.1); Scheduler 0.23.2 — [пакет scheduler 0.23.2](https://www.npmjs.com/package/scheduler/v/0.23.2).

3.1.2. **React Router** версии 7.18.4 — библиотека маршрутизации, с библиотеками **cookie** версии 1.1.1 и **set-cookie-parser** версии 2.7.3.

- Открытая лицензия: MIT.
- Правообладатели: React Router — `Copyright (c) React Training LLC 2015-2019`, `Copyright (c) Remix Software Inc. 2020-2021`, `Copyright (c) Shopify Inc. 2022-2023`; cookie — `Copyright (c) 2012-2014 Roman Shtylman`, `Copyright (c) 2015 Douglas Christopher Wilson`; set-cookie-parser — `Copyright (c) 2015 Nathan Friedly`.
- Исходный код: [github.com/remix-run/react-router, тег react-router@7.18.4](https://github.com/remix-run/react-router/tree/react-router@7.18.4), [github.com/jshttp/cookie, тег v1.1.1](https://github.com/jshttp/cookie/tree/v1.1.1), [github.com/nfriedly/set-cookie-parser, тег v2.7.3](https://github.com/nfriedly/set-cookie-parser/tree/v2.7.3).

3.1.3. **TanStack Query** версии 5.105.0 (пакеты `@tanstack/react-query` и `@tanstack/query-core`) — библиотека загрузки данных.

- Открытая лицензия: MIT.
- Правообладатель: `Copyright (c) 2021-present Tanner Linsley`.
- Исходный код: [github.com/TanStack/query, тег @tanstack/react-query@5.105.0](https://github.com/TanStack/query/tree/@tanstack/react-query@5.105.0).

3.1.4. **openapi-fetch** версии 0.13.8 — библиотека запросов к программному интерфейсу Сервиса.

- Открытая лицензия: MIT.
- Правообладатель: `Copyright (c) 2023 Drew Powers`.
- Исходный код: [github.com/openapi-ts/openapi-typescript, тег openapi-fetch@0.13.8](https://github.com/openapi-ts/openapi-typescript/tree/openapi-fetch@0.13.8).

3.1.5. **tus-js-client** версии 4.3.1 — библиотека возобновляемой загрузки файлов, с библиотеками **js-base64** версии 3.9.4, **url-parse** версии 1.5.10, **querystringify** версии 2.2.0 и **requires-port** версии 1.0.0.

- Открытые лицензии: tus-js-client, url-parse, querystringify, requires-port — MIT; js-base64 — BSD-3-Clause.
- Правообладатели: tus-js-client — `Copyright (c) 2015 tus - Resumable File Uploads`; url-parse, querystringify, requires-port — `Copyright (c) 2015 Unshift.io, Arnout Kazemier, the Contributors.`; js-base64 — `Copyright (c) 2014, Dan Kogai`.
- Исходный код: [github.com/tus/tus-js-client, тег v4.3.1](https://github.com/tus/tus-js-client/tree/v4.3.1), [github.com/dankogai/js-base64, тег v3.9.4](https://github.com/dankogai/js-base64/tree/v3.9.4), [github.com/unshiftio/url-parse, тег 1.5.10](https://github.com/unshiftio/url-parse/tree/1.5.10), [github.com/unshiftio/querystringify, тег 2.2.0](https://github.com/unshiftio/querystringify/tree/2.2.0), [github.com/unshiftio/requires-port, тег 1.0.0](https://github.com/unshiftio/requires-port/tree/1.0.0).

3.1.6. **Workbox** версии 7.4.1 (модули `workbox-window`, `workbox-core`, `workbox-precaching`, `workbox-routing`, `workbox-strategies`, `workbox-expiration`, `workbox-cacheable-response`) — библиотеки сервис-воркера, обеспечивающего работу Сервиса без подключения к сети.

- Открытая лицензия: MIT.
- Правообладатель: `Copyright 2018 Google LLC`.
- Исходный код: [github.com/GoogleChrome/workbox, тег v7.4.1](https://github.com/GoogleChrome/workbox/tree/v7.4.1).

3.1.7. **Inter** — шрифт интерфейса в составе пакета `@fontsource-variable/inter` версии 5.3.0.

- Открытая лицензия: SIL Open Font License 1.1 (OFL-1.1).
- Правообладатель: `Copyright 2016 The Inter Project Authors (https://github.com/rsms/inter)`.
- Файлы шрифта: [пакет @fontsource-variable/inter 5.3.0](https://www.npmjs.com/package/@fontsource-variable/inter/v/5.3.0), исходные файлы шрифта — [github.com/rsms/inter](https://github.com/rsms/inter).

3.2. В браузер Пользователя при использовании Локального режима передаются следующие Компоненты:

3.2.1. **Mediabunny** версии 1.61.6 — библиотека чтения видеозаписей и декодирования звука.

- Открытая лицензия: Mozilla Public License 2.0 (MPL-2.0).
- Правообладатель: автор и участники проекта Mediabunny (Vanilagy).
- Исходный код: [github.com/Vanilagy/mediabunny, тег v1.61.6](https://github.com/Vanilagy/mediabunny/tree/v1.61.6). Исходный код Mediabunny распространяется на условиях MPL-2.0.

3.2.2. **ffmpeg.wasm** версии 0.12.15 (пакет `@ffmpeg/ffmpeg`) — программный интерфейс для запуска Ядра ffmpeg.wasm.

- Открытая лицензия: MIT.
- Правообладатель: `Copyright (c) 2019 Jerome Wu`.
- Исходный код: [github.com/ffmpegwasm/ffmpeg.wasm, тег v12.15](https://github.com/ffmpegwasm/ffmpeg.wasm/tree/v12.15).

3.2.3. **Ядро ffmpeg.wasm** версии 0.12.10 (пакет `@ffmpeg/core`) — сведения приведены в разделе 4 Документа.

3.2.4. **Transformers.js** версии 4.3.1 (пакет `@huggingface/transformers`) — библиотека запуска модели распознавания речи, с включёнными в неё библиотеками **@huggingface/tokenizers** версии 0.2.0 и **@huggingface/jinja** версии 0.5.10.

- Открытые лицензии: Transformers.js, @huggingface/tokenizers — Apache License 2.0 (Apache-2.0); @huggingface/jinja — MIT.
- Правообладатель: Hugging Face; @huggingface/jinja — `Copyright (c) 2023 Hugging Face`.
- Исходный код: [github.com/huggingface/transformers.js, тег 4.3.1](https://github.com/huggingface/transformers.js/tree/4.3.1), [github.com/huggingface/tokenizers.js, тег v0.2.0](https://github.com/huggingface/tokenizers.js/tree/v0.2.0), [github.com/huggingface/huggingface.js, тег jinja-v0.5.10](https://github.com/huggingface/huggingface.js/tree/jinja-v0.5.10).

3.2.5. **ONNX Runtime Web** версии 1.31.0-dev.20260914-8d85527a0 и **onnxruntime-common** версий 1.30.0 и 1.31.0-dev.20260911-2a43ec07e — среда выполнения модели распознавания речи. Файлы среды выполнения в формате WebAssembly загружаются браузером с сайта cdn.jsdelivr.net.

- Открытая лицензия: MIT.
- Правообладатель: `Copyright (c) Microsoft Corporation.`
- Исходный код: [github.com/microsoft/onnxruntime, коммит 8d85527a010e294a26b274749f74294b2a32cec5](https://github.com/microsoft/onnxruntime/tree/8d85527a010e294a26b274749f74294b2a32cec5), [коммит 2a43ec07e67df9263c7c56c15da76cc7f74d7b32](https://github.com/microsoft/onnxruntime/tree/2a43ec07e67df9263c7c56c15da76cc7f74d7b32), [тег v1.30.0](https://github.com/microsoft/onnxruntime/tree/v1.30.0). Сведения о компонентах третьих лиц, включённых в ONNX Runtime, приведены в файле [ThirdPartyNotices.txt](https://github.com/microsoft/onnxruntime/blob/8d85527a010e294a26b274749f74294b2a32cec5/ThirdPartyNotices.txt).

3.2.6. **WebLLM** версии 0.2.86 (пакет `@mlc-ai/web-llm`) — библиотека запуска языковой модели, которая в Локальном режиме составляет конспект и главы по расшифровке. В неё включены среда выполнения **Apache TVM** (пакет `@mlc-ai/web-runtime` версии 0.28.0-dev0), библиотека токенизации **tokenizers-cpp** (пакет `@mlc-ai/web-tokenizers` версии 0.1.6), библиотека ограничения формата ответа **XGrammar** (пакет `@mlc-ai/web-xgrammar` версии 0.1.27), фрагменты описания программного интерфейса из библиотеки **openai-node**, библиотеки **loglevel** версии 1.9.2 и **tslib** версии 2.8.1.

- Открытые лицензии: WebLLM, Apache TVM, tokenizers-cpp, XGrammar, openai-node — Apache License 2.0 (Apache-2.0); loglevel — MIT; tslib — BSD Zero Clause License (0BSD).
- Правообладатели: WebLLM — `Copyright 2023-2026 WebLLM Team`; XGrammar — `Copyright (c) 2024 by XGrammar Contributors`; tokenizers-cpp — проект MLC (mlc-ai), строка об авторском праве в файле LICENSE tokenizers-cpp не заполнена правообладателем; Apache TVM — `Copyright 2019-2023 The Apache Software Foundation`; openai-node — `Copyright 2024 OpenAI`; loglevel — `Copyright (c) 2013 Tim Perry`; tslib — `Copyright (c) Microsoft Corporation.`
- Исходный код: [github.com/mlc-ai/web-llm, тег v0.2.86](https://github.com/mlc-ai/web-llm/tree/v0.2.86) (коммит c42c36670cfc426c75e53ee297443882f1ae8d84), [пакет @mlc-ai/web-runtime 0.28.0-dev0](https://www.npmjs.com/package/@mlc-ai/web-runtime/v/0.28.0-dev0), собранный из каталога `web` репозитория [github.com/apache/tvm](https://github.com/apache/tvm/tree/v0.28.dev0/web) (коммит сборки в пакете не указан, ближайший тег — v0.28.dev0), [github.com/mlc-ai/tokenizers-cpp, коммит d54e3683dc44d37163cf8e77c243b505e12a1616](https://github.com/mlc-ai/tokenizers-cpp/tree/d54e3683dc44d37163cf8e77c243b505e12a1616), из которого собран [пакет @mlc-ai/web-tokenizers 0.1.6](https://www.npmjs.com/package/@mlc-ai/web-tokenizers/v/0.1.6), [github.com/mlc-ai/xgrammar, коммит ace2321a29471130f3f64fb1882741a5547c6f36](https://github.com/mlc-ai/xgrammar/tree/ace2321a29471130f3f64fb1882741a5547c6f36), из которого собран [пакет @mlc-ai/web-xgrammar 0.1.27](https://www.npmjs.com/package/@mlc-ai/web-xgrammar/v/0.1.27), [github.com/openai/openai-node](https://github.com/openai/openai-node) (версия, из которой взяты фрагменты, в Исходном коде WebLLM не указана), [github.com/pimterry/loglevel, тег v1.9.2](https://github.com/pimterry/loglevel/tree/v1.9.2), [github.com/microsoft/tslib, тег v2.8.1](https://github.com/microsoft/tslib/tree/v2.8.1).

3.3. Модели распознавания речи загружаются браузером Пользователя с сайта huggingface.co при первом запуске Локального режима и не передаются с серверов Сервиса:

3.3.1. **Whisper tiny**, **Whisper base** и **Whisper small** в формате ONNX — репозитории [onnx-community/whisper-tiny](https://huggingface.co/onnx-community/whisper-tiny), [onnx-community/whisper-base](https://huggingface.co/onnx-community/whisper-base) и [onnx-community/whisper-small](https://huggingface.co/onnx-community/whisper-small), созданные на основе моделей [openai/whisper-tiny](https://huggingface.co/openai/whisper-tiny), [openai/whisper-base](https://huggingface.co/openai/whisper-base) и [openai/whisper-small](https://huggingface.co/openai/whisper-small).

- Открытая лицензия: программный код и веса моделей Whisper опубликованы правообладателем на условиях лицензии [MIT](https://github.com/openai/whisper/blob/main/LICENSE); в карточках моделей openai/whisper-tiny, openai/whisper-base и openai/whisper-small на сайте huggingface.co указана лицензия Apache-2.0.
- Правообладатель: `Copyright (c) 2022 OpenAI`.
- Версия: файлы моделей загружаются из основной ветки указанных репозиториев. На дату редакции Документа основная ветка соответствует коммитам ff4177021cc41f7db950912b73ea4fdf7d01d8e7 (whisper-tiny), 1846881b6b3a3024392c1eea3ad983695bc23925 (whisper-base) и 36050c46d777d46dc4b5f43f6d90574fc38f8732 (whisper-small).

3.4. Языковая модель загружается браузером Пользователя при первом составлении конспекта в Локальном режиме и не передаётся с серверов Сервиса. Веса модели загружаются с сайта huggingface.co, библиотека модели для WebGPU — с сайта raw.githubusercontent.com:

3.4.1. **Qwen2.5-1.5B-Instruct** в формате MLC с квантованием q4f32_1 — репозиторий [mlc-ai/Qwen2.5-1.5B-Instruct-q4f32_1-MLC](https://huggingface.co/mlc-ai/Qwen2.5-1.5B-Instruct-q4f32_1-MLC), созданный на основе модели [Qwen/Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct).

- Открытая лицензия: веса модели Qwen2.5-1.5B-Instruct опубликованы правообладателем на условиях лицензии [Apache-2.0](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct/blob/main/LICENSE).
- Правообладатель: `Copyright 2024 Alibaba Cloud`.
- Версия: файлы весов загружаются из основной ветки указанного репозитория. На дату редакции Документа основная ветка соответствует коммиту a822ee410075710c9673005eafa017b90136b85d, основная ветка репозитория исходной модели Qwen/Qwen2.5-1.5B-Instruct — коммиту 989aa7980e4cf806f80c7fef2b1adb7bc71aa306.
- Библиотека модели для WebGPU: файл `Qwen2-1.5B-Instruct-q4f32_1_cs1k-webgpu.wasm` из каталога `web-llm-models/v0_2_86/base` основной ветки репозитория [github.com/mlc-ai/binary-mlc-llm-libs](https://github.com/mlc-ai/binary-mlc-llm-libs/tree/00fe7a40e57e5e8eb9fef87526a4bf28ad5846c0/web-llm-models/v0_2_86/base) (на дату редакции Документа — коммит 00fe7a40e57e5e8eb9fef87526a4bf28ad5846c0), собранный проектом MLC средствами [MLC LLM](https://github.com/mlc-ai/mlc-llm) (Apache-2.0). Отдельная лицензия в репозитории библиотек не указана.

## 4. Ядро ffmpeg.wasm

4.1. Файлы Ядра ffmpeg.wasm (`/assets/ffmpeg-core-*.js` и `/assets/ffmpeg-core-*.wasm`) передаются в браузер Пользователя с серверов Сервиса только в случае, когда извлечение звука из видеозаписи средствами браузера невозможно.

4.2. Сведения о Ядре ffmpeg.wasm:

- пакет: `@ffmpeg/core` версии 0.12.10, [страница пакета](https://www.npmjs.com/package/@ffmpeg/core/v/0.12.10);
- сборка: программа FFmpeg версии n5.1.4, собранная с включением компонентов, распространяемых на условиях GNU General Public License (параметр сборки `--enable-gpl`), и библиотек, указанных в пункте 4.5 Документа;
- Открытая лицензия: GNU General Public License версии 2 или любой более поздней версии (GPL-2.0-or-later);
- правообладатели: разработчики FFmpeg (the FFmpeg developers), авторы ffmpeg.wasm и правообладатели библиотек, указанных в пункте 4.5 Документа.

4.3. Текст GNU General Public License версии 2 размещён рядом с файлами Ядра ffmpeg.wasm по адресу `https://lecturo.ru/assets/ffmpeg-core/LICENSE.txt` и опубликован Фондом свободного программного обеспечения на сайте [gnu.org](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html). Сведения о версии и Исходном коде Ядра ffmpeg.wasm размещены по адресу `https://lecturo.ru/assets/ffmpeg-core/README.txt`.

4.4. Исходный код Ядра ffmpeg.wasm:

- исходный код и сценарии сборки ffmpeg.wasm: [github.com/ffmpegwasm/ffmpeg.wasm, тег v12.15](https://github.com/ffmpegwasm/ffmpeg.wasm/tree/v12.15) (коммит 71aa99d37c02a7b4c435275ca9ef50e612f6efa1), в составе которого выпущен пакет `@ffmpeg/core` версии 0.12.10; порядок сборки определён файлом [Dockerfile](https://github.com/ffmpegwasm/ffmpeg.wasm/blob/v12.15/Dockerfile);
- исходный код FFmpeg: [github.com/FFmpeg/FFmpeg, тег n5.1.4](https://github.com/FFmpeg/FFmpeg/tree/n5.1.4) (коммит 4729204c17f756e186d622060088371d10b34f7e).

4.5. В Ядро ffmpeg.wasm включены следующие библиотеки, Исходный код которых используется при сборке в соответствии с файлом Dockerfile, указанным в пункте 4.4 Документа:

- x264, ветка 4-cores (на дату редакции Документа — коммит 33cac6b77d5b9259c552156013a817ab23119612), GPL-2.0-or-later: [github.com/ffmpegwasm/x264](https://github.com/ffmpegwasm/x264/tree/33cac6b77d5b9259c552156013a817ab23119612);
- x265, тег 3.4, GPL-2.0-or-later: [github.com/ffmpegwasm/x265](https://github.com/ffmpegwasm/x265/tree/3.4);
- libvpx, тег v1.13.1, BSD-3-Clause: [github.com/ffmpegwasm/libvpx](https://github.com/ffmpegwasm/libvpx/tree/v1.13.1);
- LAME, ветка master (на дату редакции Документа — коммит 2badea1974ae36cb8312afe99cff1e6b3b5decee), GNU Library General Public License версии 2 или любой более поздней версии (LGPL-2.0-or-later): [github.com/ffmpegwasm/lame](https://github.com/ffmpegwasm/lame/tree/2badea1974ae36cb8312afe99cff1e6b3b5decee);
- libogg, тег v1.3.4, BSD-3-Clause: [github.com/ffmpegwasm/Ogg](https://github.com/ffmpegwasm/Ogg/tree/v1.3.4);
- libtheora, тег v1.1.1, BSD-3-Clause: [github.com/ffmpegwasm/theora](https://github.com/ffmpegwasm/theora/tree/v1.1.1);
- Opus, тег v1.3.1, BSD-3-Clause: [github.com/ffmpegwasm/opus](https://github.com/ffmpegwasm/opus/tree/v1.3.1);
- libvorbis, тег v1.3.3, BSD-3-Clause: [github.com/ffmpegwasm/vorbis](https://github.com/ffmpegwasm/vorbis/tree/v1.3.3);
- zlib, тег v1.2.11, Zlib: [github.com/ffmpegwasm/zlib](https://github.com/ffmpegwasm/zlib/tree/v1.2.11);
- libwebp, тег v1.3.2, BSD-3-Clause: [github.com/ffmpegwasm/libwebp](https://github.com/ffmpegwasm/libwebp/tree/v1.3.2);
- FreeType, тег VER-2-10-4, FreeType License или GPL-2.0 по выбору лицензиата: [github.com/ffmpegwasm/freetype2](https://github.com/ffmpegwasm/freetype2/tree/VER-2-10-4);
- FriBidi, тег v1.0.9, LGPL-2.1-or-later: [github.com/fribidi/fribidi](https://github.com/fribidi/fribidi/tree/v1.0.9);
- HarfBuzz, тег 5.2.0, MIT: [github.com/harfbuzz/harfbuzz](https://github.com/harfbuzz/harfbuzz/tree/5.2.0);
- libass, тег 0.15.0, ISC: [github.com/libass/libass](https://github.com/libass/libass/tree/0.15.0);
- zimg, тег release-3.0.5, WTFPL: [github.com/sekrit-twc/zimg](https://github.com/sekrit-twc/zimg/tree/release-3.0.5).

4.6. Уведомления об авторских правах и условия лицензий библиотек, указанных в пункте 4.5 Документа, содержатся в их Исходном коде по указанным ссылкам.

## 5. Тексты лицензий

5.1. Тексты Открытых лицензий опубликованы по следующим адресам:

- MIT: [opensource.org/license/mit](https://opensource.org/license/mit);
- BSD-3-Clause: [opensource.org/license/bsd-3-clause](https://opensource.org/license/bsd-3-clause);
- BSD Zero Clause License (0BSD): [opensource.org/license/0bsd](https://opensource.org/license/0bsd);
- ISC: [opensource.org/license/isc-license-txt](https://opensource.org/license/isc-license-txt);
- Zlib: [opensource.org/license/zlib](https://opensource.org/license/zlib);
- Apache License 2.0: [apache.org/licenses/LICENSE-2.0](https://www.apache.org/licenses/LICENSE-2.0);
- Mozilla Public License 2.0: [mozilla.org/MPL/2.0](https://www.mozilla.org/en-US/MPL/2.0/);
- SIL Open Font License 1.1: [openfontlicense.org](https://openfontlicense.org/open-font-license-official-text/);
- GNU General Public License версии 2: [gnu.org/licenses/old-licenses/gpl-2.0](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html);
- GNU Lesser General Public License версии 2.1: [gnu.org/licenses/old-licenses/lgpl-2.1](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html);
- GNU Library General Public License версии 2: [gnu.org/licenses/old-licenses/lgpl-2.0](https://www.gnu.org/licenses/old-licenses/lgpl-2.0.html);
- FreeType License: [freetype.org/license](https://freetype.org/license.html);
- WTFPL: [wtfpl.net](http://www.wtfpl.net/about/).

5.2. Текст лицензии MIT, применяемый к Компонентам с указанием правообладателей, приведённых в разделе 3 Документа:

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

5.3. Текст лицензии BSD-3-Clause, применяемый к библиотеке js-base64 (`Copyright (c) 2014, Dan Kogai. All rights reserved.`):

> Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
>
> Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
>
> Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
>
> Neither the name of {{{project}}} nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission.
>
> THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

5.4. Тексты файлов NOTICE, воспроизводимые в соответствии с подпунктом (d) пункта 4 Apache License 2.0:

5.4.1. Apache TVM — файл NOTICE из [github.com/apache/tvm, тег v0.28.dev0](https://github.com/apache/tvm/blob/v0.28.dev0/NOTICE) (коммит 5398c27e76c7c858d7fae655496e68b297fc99fc). Точный коммит, из которого собран пакет `@mlc-ai/web-runtime` версии 0.28.0-dev0, в пакете не указан; использован ближайший тег, на дату редакции Документа текст файла в основной ветке совпадает:

> Apache TVM
>
> Copyright 2019-2023 The Apache Software Foundation
>
> This product includes software developed at The Apache Software Foundation (http://www.apache.org/).

5.4.2. XGrammar — файл NOTICE из [github.com/mlc-ai/xgrammar, коммит ace2321a29471130f3f64fb1882741a5547c6f36](https://github.com/mlc-ai/xgrammar/blob/ace2321a29471130f3f64fb1882741a5547c6f36/NOTICE), из которого собран пакет `@mlc-ai/web-xgrammar` версии 0.1.27:

> XGrammar
>
> Copyright (c) 2024 by XGrammar Contributors

5.5. Тексты лицензий приведены на языке оригинала.

## 6. Заключительные положения

6.1. Администрация актуализирует Документ при изменении состава или версий Компонентов. Новая редакция Документа размещается на настоящей странице с указанием даты редакции.

6.2. Обращения по вопросам использования Компонентов и запросы Исходного кода направляются Администрации по адресу электронной почты ivanov.ii@lecturo.ru.
