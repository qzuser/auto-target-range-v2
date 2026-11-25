# Runtime Web Assets

This directory is the runtime asset root for the Web console.

- Page entry points: `index.html`, `login.html`
- Legacy console JavaScript and CSS: `js/`, `css/`
- Generated session-reader bundle: `app/session.js`, `app/session.css`

Session-reader source lives in `frontend/`. Run `npm run build` there after
editing that source; do not hand-edit the generated `app/session.*` files.
