Caching with Varnish
=====================

If your instance is public and gets crawled hard enough to affect
availability, putting a caching proxy such as `Varnish`__ in front of
Patchwork can absorb most of that traffic before it reaches Django at all.
This document describes a minimal VCL configuration to get that working
safely, and lists the gotchas we know about so you don't have to rediscover
them the hard way.

This is deliberately not a complete production VCL. It covers the one thing
that's specific to Patchwork: telling Varnish which traffic is safe to cache
and which isn't. Backend health checks, grace mode, request coalescing and
the rest of a production Varnish setup are standard Django-fronting concerns
and are covered well elsewhere.

__ https://varnish-cache.org/

.. _varnish-minimal-vcl:

Minimal VCL
-----------

Patchwork already tells Varnish what's cacheable via ordinary HTTP headers:
pages rendered for anonymous users under :ref:`GATE_ANONYMOUS_ACCESS
<gate-anonymous-access>` set an explicit ``Cache-Control: public,
max-age=...``, and nothing else does. The only thing Varnish needs to be
told is to stop treating every request as unique because of its ``Cookie``
header:

.. code-block:: vcl

   sub vcl_recv {
       # A session cookie means this request needs Django to see it -
       # don't try to cache it.
       if (req.http.Cookie ~ "sessionid=") {
           return (pass);
       }

       # No session cookie: this is anonymous traffic. Drop the Cookie
       # header entirely so requests that differ only in some unrelated
       # cookie (analytics, a CDN, whatever) still share a cache entry.
       unset req.http.Cookie;
   }

That's it. Everything else - which pages are cacheable, and for how long -
is left to Patchwork's own ``Cache-Control`` headers and to Varnish's
built-in ``vcl_backend_response``/``vcl_deliver`` logic, which already knows
not to cache responses carrying ``Set-Cookie`` or ``Cache-Control:
private``/``no-store``.

Gotchas
-------

**Anonymous pages with no explicit ``Cache-Control`` still get cached.**
This is the one most worth remembering. Once ``Cookie`` is stripped,
*every* anonymous ``GET``/``HEAD`` response becomes cacheable as far as
Varnish's default admission logic is concerned - not just the ones
Patchwork explicitly marked ``public``. A response with no
``Cache-Control`` header at all still gets Varnish's ``default_ttl``
(120 seconds out of the box) rather than being treated as uncacheable. If
``GATE_ANONYMOUS_ACCESS`` is off, or for any view that doesn't set its own
cache header, this means one anonymous page render gets served to *every*
anonymous visitor for up to that long. That's often fine - it's one more
layer of the same "shared, unkeyed-by-cookie" caching this setup is for -
but it's easy to assume nothing is cached unless Patchwork says so, and
that's not true. If some view must never be shared this way, it needs to
set its own ``Cache-Control: private`` or ``no-store``, or you need to
special-case its path in VCL.

**Don't cache anything with ``Set-Cookie``, even by accident.** Rendering a
form with a CSRF token sets a ``csrftoken`` cookie via ``Set-Cookie``, even
for anonymous visitors (the login and registration pages, for example).
Varnish's built-in VCL already refuses to cache such responses - the
anonymous-served pages added for ``GATE_ANONYMOUS_ACCESS`` are verified not
to render any CSRF-bearing forms, precisely so they stay cacheable. If you
add custom ``vcl_backend_response``/``vcl_deliver`` logic, make sure it
doesn't override that safety net (e.g. by forcing ``return (deliver)``
before the built-in ``Set-Cookie`` check runs). Caching a response with
someone else's CSRF token in it means handing it out to everyone.

**The session cookie name is configurable.** The regex above assumes
Django's default ``SESSION_COOKIE_NAME`` of ``sessionid``. If your
``settings.py`` overrides it, update the VCL to match, or every real session
gets treated as anonymous and cached for other visitors.

**Stripping ``Cookie`` is all-or-nothing.** The rule above drops every
cookie for anonymous traffic, not just the session cookie. That's fine if
Patchwork is the only thing on the domain, but if you're running it behind
a shared frontend that relies on some other cookie for anonymous visitors
(an A/B test, a consent banner, anything), stripping all cookies will break
that too. Narrow the ``unset`` to just the session cookie if you need to
keep others around, at the cost of a less effective cache key.

**Let the backend set the TTL.** ``ANONYMOUS_LIST_CACHE_TIMEOUT`` controls
how stale Patchwork's own cache entry may be, and the ``max-age`` on the
response is however long that entry has left, so the two never add up. If
you add VCL that unconditionally overrides ``beresp.ttl``, you can end up
with Varnish serving a page well past the staleness window the page itself
claims to have. Let the backend's own ``Cache-Control`` drive the TTL rather
than hardcoding one.

**Redirects to the login page are cacheable, and that's fine.** Once
``GATE_ANONYMOUS_ACCESS`` gates a URL, an anonymous request gets a ``302``
to the login page. That response has no session cookie to vary on and is
identical for every anonymous visitor of that URL, so it's safe for Varnish
to cache it under the default TTL rule above - it just saves Django the
trip. Nothing special to configure here, just don't be surprised by it
turning up as a cache hit.

**TLS termination needs to be declared to Django.** If Varnish sits behind
your TLS terminator (or terminates TLS itself and talks HTTP to Django),
make sure Django is told the original scheme via ``SECURE_PROXY_SSL_HEADER``
and that the proxy sets that header truthfully. Otherwise Django believes
every request is plain HTTP, which breaks CSRF's origin check and secure
cookies. This isn't specific to Patchwork, but it's an easy thing to miss
when a caching layer is the first proxy you add.

**Non-``GET``/``HEAD`` requests are never cached by default, and should
stay that way.** Patch submission, login, and everything else that mutates
state goes through ``POST``, which Varnish's built-in VCL passes straight
through. Don't add logic that starts caching those.
