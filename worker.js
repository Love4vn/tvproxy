export default {
  async fetch(request, env, ctx) {
    const urlObj = new URL(request.url);
    const targetUrl   = urlObj.searchParams.get("url");
    const refParam    = urlObj.searchParams.get("ref");
    const originParam = urlObj.searchParams.get("origin");
    const uaParam     = urlObj.searchParams.get("ua");

    if (!targetUrl) {
      return new Response("❌ Missing ?url= parameter", { status: 400, headers: { "Access-Control-Allow-Origin": "*" } });
    }

    try {
      // Fallback rules — SẼ ĐƯỢC TỰ ĐỘNG CẬP NHẬT BỞI GITHUB ACTIONS
      const fallbackRules = {
        "strmd.st":          { Origin: "https://embed.st",              Referer: "https://embed.st/" },
        "edgestream4.pro":   { Origin: "https://embed.st",              Referer: "https://embed.st/" },
        "edgestream5.pro":   { Origin: "https://embed.st",              Referer: "https://embed.st/" },
        "edgestream6.pro":   { Origin: "https://embed.st",              Referer: "https://embed.st/" },
        "edgestream7.pro":   { Origin: "https://embed.st",              Referer: "https://embed.st/" },
        "hockey.do":         { Origin: "https://play.matchli.st",       Referer: "https://play.matchli.st/" },
        "dudestream1.com":   { Origin: "https://dudestream1.com",       Referer: "https://dudestream1.com/" },
        "resports.cfd":      { Origin: "https://resports.cfd",          Referer: "https://resports.cfd/" },
        "tophdstreams.com":  { Origin: "https://live.tophdstreams.com", Referer: "https://live.tophdstreams.com/" },
        "sportspatrika.com": { Origin: "https://embed.sportspatrika.com", Referer: "https://embed.sportspatrika.com/" },
        "tnt-usa.biz":       { Origin: "https://tnt-usa.biz",           Referer: "https://tnt-usa.biz/" },
        "shd247.world":      { Origin: "https://shd247.world",          Referer: "https://shd247.world/" },
        // [XOILAC_RULES_START]
        "quickscoreboardz.com":      { Origin: "https://xl365.domainkqt.cc", Referer: "https://xl365.domainkqt.cc/" },
        "domaincdn.cc":              { Origin: "https://xl365.domainkqt.cc", Referer: "https://xl365.domainkqt.cc/" },
        "jorvakstreamcache.com":     { Origin: "https://xl365.domainkqt.cc", Referer: "https://xl365.domainkqt.cc/" },
        "zundrixmediapipeline.com":  { Origin: "https://xl365.domainkqt.cc", Referer: "https://xl365.domainkqt.cc/" },
        // [XOILAC_RULES_END]
      };

      const customHeaders = {
        "User-Agent":      uaParam || "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept":          "*/*",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
      };

      if (refParam)    customHeaders["Referer"] = refParam;
      if (originParam) customHeaders["Origin"]  = originParam;

      const targetHost = new URL(targetUrl).hostname;
      for (const ruleHost in fallbackRules) {
        if (targetHost.includes(ruleHost)) {
          if (!refParam)    customHeaders["Referer"] = fallbackRules[ruleHost].Referer;
          if (!originParam) customHeaders["Origin"]  = fallbackRules[ruleHost].Origin;
          break;
        }
      }

      const resp = await fetch(targetUrl, {
        headers: customHeaders,
        redirect: "follow",
      });

      if (!resp.ok) {
        return new Response(`Proxy failed: ${resp.status} ${resp.statusText}`, { 
          status: resp.status, 
          headers: { "Access-Control-Allow-Origin": "*" } 
        });
      }

      const contentType = resp.headers.get("content-type") || "";

      if (contentType.includes("mpegurl") || targetUrl.includes(".m3u8")) {
        const text    = await resp.text();
        const baseUrl = targetUrl.substring(0, targetUrl.lastIndexOf("/") + 1);

        const carry = [];
        if (refParam)    carry.push("ref="    + encodeURIComponent(refParam));
        if (originParam) carry.push("origin=" + encodeURIComponent(originParam));
        if (uaParam)     carry.push("ua="     + encodeURIComponent(uaParam));
        const extra = carry.length ? "&" + carry.join("&") : "";

        const workerBase = urlObj.origin + urlObj.pathname;

        const rewritten = text.split("\n").map(line => {
          const t = line.trim();
          if (!t) return line;
          if (t.startsWith("#")) {
            return t.replace(/URI="([^"]+)"/g, (_, uri) => {
              const abs = uri.startsWith("http") ? uri : baseUrl + uri;
              return `URI="${workerBase}?url=${encodeURIComponent(abs)}${extra}"`;
            });
          }
          const abs = t.startsWith("http") ? t : baseUrl + t;
          return `${workerBase}?url=${encodeURIComponent(abs)}${extra}`;
        }).join("\n");

        return new Response(rewritten, {
          status: 200,
          headers: {
            "Content-Type": "application/vnd.apple.mpegurl",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
          },
        });
      }

      return new Response(resp.body, {
        status: resp.status,
        headers: {
          "Content-Type": contentType || "video/mp2t",
          "Cache-Control": "no-store",
          "Access-Control-Allow-Origin": "*",
        },
      });
    } catch (err) {
      return new Response("Worker error: " + err.message, { 
        status: 500, 
        headers: { "Access-Control-Allow-Origin": "*" } 
      });
    }
  },
};
