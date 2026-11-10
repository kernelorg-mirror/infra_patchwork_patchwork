The REST API
============

Patchwork provides a REST API. This API can be used to retrieve and modify
information about patches, projects and more.

This guide provides an overview of how one can interact with the REST API. For
detailed information on type and response format of the various resources
exposed by the API, refer to the web browsable API. This can be found at:

    https://patchwork.example.com/api/1.4/

where `patchwork.example.com` refers to the URL of your Patchwork instance.

If all you want is reference guides, skip straight to :ref:`rest-api-schemas`.

.. important::

   The REST API can be enabled/disabled by the administrator: it may not be
   available in every instance. Refer to ``/about`` on your given instance for
   the status of the API, e.g.

       https://patchwork.ozlabs.org/about

.. versionadded:: 2.0

   The REST API was introduced in Patchwork v2.0. Users of earlier Patchwork
   versions should instead refer to :doc:`XML-RPC API </api/xmlrpc>`
   documentation.

.. versionchanged:: 2.1

   The API version was bumped to v1.1 in Patchwork v2.1. The older v1.0 API is
   still supported. For more information, refer to :ref:`rest-api-versions`.

.. versionchanged:: 2.2

   The API version was bumped to v1.2 in Patchwork v2.2. The older APIs are
   still supported. For more information, refer to :ref:`rest-api-versions`.

.. versionchanged:: 3.1

   The API version was bumped to v1.3 in Patchwork v3.1. The older APIs are
   still supported. For more information, refer to :ref:`rest-api-versions`.

.. versionchanged:: 3.3

   The API version was bumped to v1.4 in Patchwork v3.3. The older APIs are
   still supported. For more information, refer to :ref:`rest-api-versions`.

Getting Started
---------------

The easiest way to start experimenting with the API is to use the web browsable
API, as described above.

REST APIs run over plain HTTP(S), thus, the API can be interfaced using
applications or libraries that support this widespread protocol. One such
application is `curl`_, which can be used to both retrieve and send information
to the REST API. For example, to get the version of the REST API for a
Patchwork instance hosted at `patchwork.example.com`, run:

.. code-block:: shell

    $ curl -s 'https://patchwork.example.com/api/1.4/' | python -m json.tool
    {
        "bundles": "https://patchwork.example.com/api/1.4/bundles/",
        "covers": "https://patchwork.example.com/api/1.4/covers/",
        "events": "https://patchwork.example.com/api/1.4/events/",
        "patches": "https://patchwork.example.com/api/1.4/patches/",
        "people": "https://patchwork.example.com/api/1.4/people/",
        "projects": "https://patchwork.example.com/api/1.4/projects/",
        "series": "https://patchwork.example.com/api/1.4/series/",
        "users": "https://patchwork.example.com/api/1.4/users/"
    }


In addition, a huge variety of libraries are available for interacting with and
parsing the output of REST APIs. The `requests`_ library is wide-spread and
well-supported. To repeat the above example using `requests`:, run

.. code-block:: pycon

    $ python
    >>> import json
    >>> import requests
    >>> r = requests.get('https://patchwork.example.com/api/1.4/')
    >>> print(json.dumps(r.json(), indent=2))
    {
        "bundles": "https://patchwork.example.com/api/1.4/bundles/",
        "covers": "https://patchwork.example.com/api/1.4/covers/",
        "events": "https://patchwork.example.com/api/1.4/events/",
        "patches": "https://patchwork.example.com/api/1.4/patches/",
        "people": "https://patchwork.example.com/api/1.4/people/",
        "projects": "https://patchwork.example.com/api/1.4/projects/",
        "series": "https://patchwork.example.com/api/1.4/series/",
        "users": "https://patchwork.example.com/api/1.4/users/"
    }

Tools like `curl` and libraries like `requests` can be used to build anything
from small utilities to full-fledged clients targeting the REST API. For an
overview of existing API clients, refer to :doc:`/usage/clients`.

.. tip::

    While you can do a lot with existing installations, it's possible that you
    might not have access to all resources or may not wish to modify any
    existing resources. In this case, it might be better to :doc:`deploy your
    own instance of Patchwork locally </development/installation>` and
    experiment with that instead.

Versioning
----------

By default, all requests will receive the latest version of the API: currently
``1.4``:

.. code-block:: http

    GET /api HTTP/1.1

You should explicitly request this version through the URL to prevent API
changes breaking your application:

.. code-block:: http

    GET /api/1.4 HTTP/1.1

Older API versions will be deprecated and removed over time. For more
information, refer to :ref:`rest-api-versions`.

Schema
------

Responses are returned as JSON. Blank fields are returned as ``null``, rather
than being omitted. Timestamps use the ISO 8601 format, times are by default
in UTC::

    YYYY-MM-DDTHH:MM:SSZ

Requests should use either query parameters or form-data, depending on the
method. Further information is provided `below <rest_parameters>`__.

Summary Representations
~~~~~~~~~~~~~~~~~~~~~~~

Some resources are particularly large or expensive to compute. When listing
these resources, a summary representation is returned that omits certain
fields.  To get all fields, fetch the detailed representation. For example,
listing patches will return summary representations for each patch:

.. code-block:: http

    GET /patches HTTP/1.1

Detailed Representations
~~~~~~~~~~~~~~~~~~~~~~~~

When fetching an individual resource, all fields will be returned. For example,
fetching a patch with an ID of ``123`` will return all available fields for
that particular resource:

.. code-block:: http

    GET /patches/123 HTTP/1.1

.. _rest_parameters:

Parameters
----------

Most API methods take optional parameters. For ``GET`` requests, these
parameters are mostly used for filtering and should be passed as a HTTP query
string parameters:

.. code-block:: shell

    $ curl 'https://patchwork.example.com/api/patches?state=under-review'

For all other types of requests, including ``POST`` and ``PATCH``, these
parameters should be encoded as JSON with a ``Content-Type`` of
``application/json`` or passed as form-encoded data:

.. code-block:: shell

    $ curl -X PATCH \
      --header "Content-Type: application/json" \
      --data '{"state":"under-review"}' \
      'http://localhost:8000/api/patches/123/'

.. code-block:: shell

    $ curl -X PATCH \
      --form 'state=under-review' \
      'https://patchwork.example.com/api/patches/123'

.. important::

    If you do not include the ``Content-Type`` header in your request, you will
    receive a ``HTTP 200 (OK)`` but the resource will not be updated. This
    header **must** be included.

.. versionchanged:: 2.1

   API version 1.1 allows filters to be specified multiple times. Prior to
   this, only the last value for a given filter key would be used.

Authentication
--------------

Patchwork supports authentication using your username and password (basic
authentication) or with a token (token authentication). The latter is
recommended.

To authenticate with token authentication, you must first obtain a token. This
can be done from your profile, e.g. https://patchwork.example.com/user.
Once you have a token, run:

.. code-block:: shell

    $ curl -H "Authorization: Token ${token}" \
        'https://patchwork.example.com/api/'

To authenticate using basic auth, you should use your Patchwork username and
password. To do this, run:

.. code-block:: shell

    $ curl -u ${username}:${password} \
        'https://patchwork.example.com/api/'

Not all resources require authentication. Those that do will return ``404 (Not
Found)`` if authentication is not provided to avoid leaking information.

Pagination
----------

Requests that return multiple items will be paginated by 30 items by default,
though this can vary from instance to instance. You can change page using the
``?page`` parameter. You can also set custom page sizes up to 100 on most
endpoints using the ``?per_page`` parameter.

.. code-block:: shell

    $ curl 'https://patchwork.example.com/api/patches?page=2&per_page=100'

Link Header
~~~~~~~~~~~

The `Link header`_ includes pagination information::

    Link: <https://patchwork.example.com/api/patches?page=3&per_page=100>; rel="next",
      <https://patchwork.example.com/api/patches?page=50&per_page=100>; rel="last"

The possible ``rel`` values are:

.. list-table::
   :header-rows: 1

   * - Name
     - Description
   * - ``next``
     - The link relation for the immediate next page of results.
   * - ``last``
     - The link relation for the last page of results.
   * - ``first``
     - The link relation for the first page of results.
   * - ``prev``
     - The link relation for the immediate previous page of results.

.. _rest-api-clients:

Writing Well-Behaved Clients
----------------------------

A Patchwork instance is usually shared by many people and many scripts. A
client that polls in a loop can easily cost the server more than everyone
else combined, often without its author knowing. These practices keep your
client fast and keep the instance available for everyone.

Say who you are
~~~~~~~~~~~~~~~

Send your API token with every request, including ``GET`` requests, and a
``User-Agent`` that names your tool and says how to reach you:

.. code-block:: shell

    $ curl -H "Authorization: Token ${token}" \
        -A 'my-ci-bot/1.0 (+https://example.com/my-ci-bot)' \
        'https://patchwork.example.com/api/1.4/projects/'

If your client causes a problem, this lets the administrators contact you
instead of blocking you.

Ask what changed, not for everything
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To follow a project, poll the events API with ``since`` set to the date of
the newest event you have already seen, and filter on the categories you
care about:

.. code-block:: shell

    $ curl 'https://patchwork.example.com/api/1.4/events/?project=myproject&category=series-completed&category=patch-state-changed&since=2026-11-10T12:00:00'

This returns only what happened since your last poll, instead of the same
list of patches every time.

Fetch a series in one request
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To learn where each patch in a series stands, list them with one request
to ``/api/1.4/patches/?series=<id>``. Each patch in the list carries its
``state`` and ``name``, but not its diff. Do not fetch the patches one by
one: a patch's own endpoint returns its full diff, which is the most
expensive thing the API serves.

Narrow down your requests
~~~~~~~~~~~~~~~~~~~~~~~~~

Always pass ``project`` when you list or search. A search with ``q``, or an
ordering such as ``order=name``, has to scan every project when it is not
narrowed down. Instances may refuse such requests with ``400 Bad Request``;
the error message says which parameters to add.

Use fewer, larger pages: set ``per_page`` to the largest value the instance
allows, and stop following ``next`` links once you have what you need.

Make one request at a time
~~~~~~~~~~~~~~~~~~~~~~~~~~

Send requests one after another, or at most a few at a time. A burst of
parallel requests is no faster for you once the server is busy, and it can
take up every worker the instance has.

Do not download the same thing twice
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Patch, cover letter and series downloads (``/mbox/`` and ``/raw/``) carry an
``ETag``. Keep it, and send it back in an ``If-None-Match`` header the next
time: if nothing has changed, you get an empty ``304 Not Modified``.

Back off when something goes wrong
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- On ``429 Too Many Requests`` or ``503 Service Unavailable``, wait for as
  long as the ``Retry-After`` header says before you try again.
- On any other ``5xx`` error, wait before retrying, starting at several
  seconds and doubling the wait each time. Retrying at once only adds to
  whatever is already wrong.
- When the server comes back after an outage, catch up slowly instead of
  sending everything you missed at once.
- Do not retry other ``4xx`` errors: the same request will fail again.

.. _rest-api-versions:

Supported Versions
------------------

.. csv-table::
   :header: "API Version", "Since", "Supported?"

   1.0, 2.0, ✓
   1.1, 2.1, ✓
   1.2, 2.2, ✓
   1.3, 3.1, ✓
   1.4, 3.3, ✓

Further information about this and more can typically be found in
:doc:`the release notes </releases/index>`.

.. _rest-api-schemas:

Schemas
-------

Auto-generated schema documentation is provided below.

.. toctree::

   /api/rest/schemas/v1.0
   /api/rest/schemas/v1.1
   /api/rest/schemas/v1.2
   /api/rest/schemas/v1.3
   /api/rest/schemas/v1.4

.. Links

.. _curl: https://curl.haxx.se/
.. _requests: http://docs.python-requests.org/en/master/
.. _Link header: https://tools.ietf.org/html/rfc5988
