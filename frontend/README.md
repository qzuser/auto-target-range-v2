# Web Session Reader

This directory builds only the React session-reader layer. The legacy console
HTML, CSS, and JavaScript remain runtime assets in
`src/spiritscout/web/static/`.

`npm run build` writes `session.js` and `session.css` into
`src/spiritscout/web/static/app/`; those two files are packaged runtime output
and must be committed with their source changes.
