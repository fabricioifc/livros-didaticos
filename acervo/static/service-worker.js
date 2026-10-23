const offlinePage = `<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#f6f7f5">
  <title>Sem conexão — Acervo IFC</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    * { box-sizing: border-box; }
    body { min-height: 100vh; margin: 0; padding: 24px; display: grid; place-items: center; background: #f6f7f5; color: #26372b; }
    main { width: min(100%, 390px); padding: 32px 24px; border: 1px solid #e1e8e1; border-radius: 12px; background: #fff; text-align: center; }
    .mark { width: 54px; height: 54px; margin: 0 auto 20px; border-radius: 12px; display: grid; place-items: center; background: #174e38; color: #fff; font-size: 16px; font-weight: 800; }
    h1 { margin: 0 0 10px; font-size: 22px; }
    p { margin: 0; color: #637067; font-size: 14px; line-height: 1.6; }
    button { margin-top: 22px; padding: 10px 16px; border: 0; border-radius: 6px; background: #174e38; color: #fff; font: inherit; font-size: 13px; font-weight: 600; cursor: pointer; }
    button:focus-visible { outline: 3px solid #83ad75; outline-offset: 3px; }
    @media (prefers-color-scheme: dark) {
      body { background: #0c100e; color: #e1e9e3; }
      main { border-color: #39423b; background: #171d19; }
      p { color: #b5c0b8; }
      button { background: #2a7350; }
    }
  </style>
</head>
<body>
  <main>
    <div class="mark" aria-hidden="true">IFC</div>
    <h1>Sem conexão</h1>
    <p>O Acervo IFC precisa de internet para carregar os dados. Conecte-se à rede e tente novamente.</p>
    <button type="button" onclick="location.reload()">Tentar novamente</button>
  </main>
</body>
</html>`;

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(() => new Response(offlinePage, {
      status: 200,
      headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
    }))
  );
});
