export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (url.pathname === "/") return new Response(null, { status: 302, headers: { location: "https://www.rrrosmontis.icu/services/slm/" } });
    return new Response("Not Found", { status: 404 });
  }
};
