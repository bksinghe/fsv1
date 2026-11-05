"""✨ Staggered result entrance — the single source for how result cards appear.

Studied from the GitHub reference (`JoneySin/v5`'s `staggerCards()` / `cardEnter`)
and rebuilt for fsv1: one CSS keyframe set + one JS engine, shipped on every page
through `SITE_CSS` / `SITE_JS`. Any result grid opts in by putting `rv-enter` on its
top-level cards and calling `RevealCards.reveal(container)` after a render; a panel
that is already visible uses `RevealCards.stagger(selector)`. No page owns a copy
of the keyframes, the observer or the stagger timing.

Contract (semantic, like the `vm-*` classes in `mode_assets.py`):
  * `rv-enter`  — card starts hidden; remove it to show the card without animation
  * `in`        — the engine adds this to start the spring; both classes are cleaned
                  up afterwards so hover/press transforms are not blocked
  * nested cards (variants inside an open group) deliberately opt out, so they are
    visible as soon as the group expands — the same rule v5 applies to nested cards.
"""

REVEAL_CSS = r"""
/* ✨ Result cards rise, overshoot slightly and settle — one shared spring.
   `.rv-enter` starts hidden; RevealCards adds `in` when a card scrolls into view. */
@keyframes rvEnter{from{opacity:0}to{opacity:1}}
/* Opacity-only reveal avoids transform contention with card/image effects and lets
   already-loaded posters become visible almost immediately. */
.rv-enter{opacity:0}
.rv-enter.in{animation:rvEnter .22s ease-out forwards}
/* The reference's hover-lift has a press response too; the lift stays with each
   card's own CSS, this shared line covers every result card on all three pages. */
.vcard:active,.gcard:active{transform:scale(.97);transition:transform .1s}
/* Shimmer placeholders shown while a fresh result batch is being fetched. */
.rv-skel{pointer-events:none}
.rv-skel .vbody{min-height:40px}
.rv-skel .rv-line{height:11px;border-radius:6px;background:var(--bg3);margin:5px 0;
animation:rvPulse 1.1s ease-in-out infinite alternate}
.rv-skel .rv-line.short{width:55%}
@keyframes rvPulse{from{opacity:.42}to{opacity:1}}
@media(prefers-reduced-motion:reduce){
.rv-enter,.rv-enter.in,.vcard:active,.gcard:active{
animation:none!important;opacity:1!important;transform:none!important}
.rv-skel .rv-line{animation:none;opacity:.7}
}
"""

REVEAL_JS = r"""
/* ✨ window.RevealCards — one engine for every result grid (web/reveal_assets.py). */
(function(){
  var DUR=0.22, STEP=0.03, MAX=4;
  function reduce(){
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }
  function show(c){
    if(!c) return;
    c.classList.remove('rv-enter','in');
    c.style.animationDelay='';
  }
  function pending(container, selector){
    return Array.prototype.filter.call(
      container.querySelectorAll(selector || '.rv-enter'),
      function(c){ return c.classList.contains('rv-enter') && !c.classList.contains('in'); });
  }
  /* Scroll-triggered reveal for listing grids. Safe to call again after "Show more":
     cards that already ran have had their classes cleaned up, so only new ones run. */
  function reveal(container, selector){
    if(!container) return;
    var cards=pending(container, selector);
    if(!cards.length) return;
    if(!('IntersectionObserver' in window) || reduce()){
      cards.forEach(show); return;
    }
    var seen=0;
    var obs=new IntersectionObserver(function(entries){
      entries.forEach(function(e){
        if(!e.isIntersecting) return;
        var c=e.target, delay=Math.round(Math.min(seen++,MAX)*STEP*1000)/1000;
        c.style.animationDelay=delay+'s';
        c.classList.add('in');
        setTimeout(function(){ show(c); }, (DUR+delay)*1000);
        obs.unobserve(c);
      });
    },{threshold:.08});
    cards.forEach(function(c){ obs.observe(c); });
  }
  /* Immediate reveal for panels already on screen (detail tabs, gallery, media). */
  function stagger(selector){
    var els=Array.prototype.filter.call(
      document.querySelectorAll(selector || '.rv-enter'),
      function(e){ return e.classList.contains('rv-enter') && !e.classList.contains('in'); });
    var noMotion=reduce();
    els.forEach(function(e,i){
      var delay=noMotion?0:Math.round(Math.min(i,4)*25)/1000;
      if(!noMotion) e.style.animationDelay=delay+'s';
      e.classList.add('in');
      setTimeout(function(){ show(e); }, (DUR+delay)*1000);
    });
  }
  window.RevealCards={reveal:reveal, stagger:stagger, show:show};
})();
"""
