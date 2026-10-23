# syntax=docker/dockerfile:1
#
# Packages the Old Irish Wordnet with a prebuilt EWE web server (read-only, no `edit` feature).
# EWE is compiled outside the image so the image only carries the artifacts:
#
#   (cd ../ewe/ewe_dioxus && dx bundle --platform web --release)
#   docker build --build-context ewe=../ewe/target/dx/ewe/release/web -t sga-wordnet .
#   docker run -d --name sga-wordnet -p 8080:8080 --restart unless-stopped sga-wordnet
#
# The databases are built from src/yaml and data/ on the first request, so the first page load
# Release files for the Downloads page are not in git; add `-v /path/to/downloads:/app/downloads:ro`.
# after a fresh start is slow. To keep them across container re-creations, add
# `-v sga-wordnet-db:/app/db` and set database/corpus_database to "db/..." in settings.toml.

FROM debian:bookworm-slim
RUN useradd --system --create-home --home-dir /app ewe
WORKDIR /app
# `server` serves the client bundle from the `public` directory beside the executable.
COPY --from=ewe server ./server
COPY --from=ewe public ./public
COPY settings.toml downloads.toml ./
COPY branding branding
COPY src/yaml src/yaml
COPY data/sga_incomplete.teanga.yaml data/
RUN mkdir db && chown -R ewe:ewe /app
USER ewe
ENV IP=0.0.0.0 PORT=8080
EXPOSE 8080
CMD ["./server"]
