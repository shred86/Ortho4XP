import os
import time
import io
import bz2
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor
import requests
import numpy
from shapely import geometry, ops
import O4_UI_Utils as UI
import O4_File_Names as FNAMES
from O4_Version import version as O4XP_VERSION

# Default overpass_server_choice if not in config
overpass_server_choice = "random"
max_osm_tentatives = 8

# Overpass QL [timeout:] setting sent with every request.  Declaring the
# timeout explicitly lets the server scheduler plan around our patience
# instead of assuming its default.  The HTTP read timeout is kept slightly
# larger so a query the server is still legitimately computing is not
# aborted client-side.
overpass_query_timeout_seconds = 180
http_connect_timeout_seconds = 30
http_read_timeout_seconds = overpass_query_timeout_seconds + 30


def _load_overpass_servers() -> dict:
    """Create dictionary from overpass_servers.txt."""
    servers = {}
    try:
        with open(FNAMES.resource_path("overpass_servers.txt"), "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, url = line.partition("=")
                    key, url = key.strip(), url.strip()
                    if key and url:
                        servers[key] = url
    except Exception as e:
        UI.lvprint(1, e)
    return servers


overpass_servers = _load_overpass_servers()


class OSM_layer:
    def __init__(self):
        self.dicosmn = {}  # keys are ints (ids) and values are tuple of (lat,lon)
        self.dicosmn_reverse = {}  # reverese of the previous one
        self.dicosmw = {}
        self.next_node_id = -1
        self.next_way_id = -1
        self.next_rel_id = -1
        # rels already sorted out and containing nodeids rather than wayids
        self.dicosmr = {}
        # original rels containing wayids only, not sorted and/or reversed
        self.dicosmrorig = {}
        # ids of objects directly queried, not of child or
        # parent objects pulled indirectly by queries. Since
        # osm ids are only unique per object type we need one for each:
        self.dicosmfirst = {"n": set(), "w": set(), "r": set()}
        self.dicosmtags = {"n": {}, "w": {}, "r": {}}
        self.dicosm = [
            self.dicosmn,
            self.dicosmw,
            self.dicosmr,
            self.dicosmrorig,
            self.dicosmfirst,
            self.dicosmtags,
        ]

    def update_dicosm(self, osm_input, input_tags=None, target_tags=None):
        # input_tags (dict or None) are the input query tags (per osm type)
        # target_tags (dict or None) are the the tags which should be kept
        # (per osm type) It is expected that if not None the target_tags
        # contains the input_tags
        initnodes = len(self.dicosmn)
        initways = len(self.dicosmfirst["w"])
        initrels = len(self.dicosmfirst["r"])
        dicosmn_id_map = {}
        dicosmw_id_map = {}
        # osm_input may either refer to an osm filename (e.g. cached data) or
        # to a xml bytestring (direct download)
        if isinstance(osm_input, str):
            osm_file_name = osm_input
            try:
                if osm_file_name[-4:] == ".bz2":
                    pfile = bz2.open(osm_file_name, "rt", encoding="utf-8")
                else:
                    pfile = open(osm_file_name, "r", encoding="utf-8")
            except:
                UI.vprint(
                    1,
                    "    Could not open",
                    osm_file_name,
                    "for reading (corrupted ?).",
                )
                return 0
        elif isinstance(osm_input, bytes):
            pfile = io.StringIO(osm_input.decode(encoding="utf-8"))
        first_line = pfile.readline()
        if "<osm " not in first_line:
            first_line = pfile.readline()
        separator = "'" if "'" in first_line else '"'
        normal_exit = False
        for line in pfile:
            items = line.split(separator)
            if "<node id=" in items[0]:
                osmtype = "n"
                osmid = items[1]
                for j in range(0, len(items)):
                    if items[j] == " lat=":
                        latp = float(items[j + 1])
                    elif items[j] == " lon=":
                        lonp = float(items[j + 1])
                if (lonp, latp) in self.dicosmn_reverse:
                    true_osmid = self.dicosmn_reverse[(lonp, latp)]
                    dicosmn_id_map[osmid] = true_osmid
                    osmid = true_osmid
                else:
                    true_osmid = self.next_node_id
                    dicosmn_id_map[osmid] = true_osmid
                    osmid = true_osmid
                    self.dicosmn_reverse[(lonp, latp)] = osmid
                    self.dicosmn[osmid] = (lonp, latp)
                    self.next_node_id -= 1
            elif "<way id=" in items[0]:
                osmtype = "w"
                osmid = items[1]
                true_osmid = self.next_way_id
                self.next_way_id -= 1
                dicosmw_id_map[osmid] = true_osmid
                osmid = true_osmid
                self.dicosmw[osmid] = []
                if not input_tags:
                    self.dicosmfirst["w"].add(osmid)
            elif "<nd ref=" in items[0]:
                self.dicosmw[osmid].append(dicosmn_id_map[items[1]])
            elif "<relation id=" in items[0]:
                osmtype = "r"
                osmid = items[1]
                true_osmid = self.next_rel_id
                self.next_rel_id -= 1
                osmid = true_osmid
                self.dicosmr[osmid] = {"outer": [], "inner": []}
                self.dicosmrorig[osmid] = {"outer": [], "inner": []}
                dico_rel_check = {"inner": {}, "outer": {}}
                if not input_tags:
                    self.dicosmfirst["r"].add(osmid)
            elif "<member type=" in items[0]:
                role = items[5]
                if items[1] != "way" or role not in ("outer", "inner"):
                    if items[1] == "node":
                        continue  # not necessary to report these
                    UI.lvprint(
                        2,
                        "Relation id=",
                        osmid,
                        "contains a member of type",
                        "'" + items[1] + "'",
                        "and role",
                        "'" + role + "'",
                        "which was not treated (only deal with 'ways' of role ",
                        "'inner' or 'outer').",
                    )
                    continue
                try:
                    wayid = dicosmw_id_map[items[3]]
                except:
                    continue
                self.dicosmrorig[osmid][role].append(wayid)
                endpt1 = self.dicosmw[wayid][0]
                endpt2 = self.dicosmw[wayid][-1]
                if endpt1 == endpt2:
                    self.dicosmr[osmid][role].append(self.dicosmw[wayid])
                else:
                    if endpt1 in dico_rel_check[role]:
                        dico_rel_check[role][endpt1].append(wayid)
                    else:
                        dico_rel_check[role][endpt1] = [wayid]
                    if endpt2 in dico_rel_check[role]:
                        dico_rel_check[role][endpt2].append(wayid)
                    else:
                        dico_rel_check[role][endpt2] = [wayid]
            elif "<tag k=" in items[0]:
                # Do we need to catch that tag ?
                if (
                    (not input_tags)
                    or (("all", "") in target_tags[osmtype])
                    or ((items[1], "") in target_tags[osmtype])
                    or ((items[1], items[3]) in target_tags[osmtype])
                ):
                    if osmid not in self.dicosmtags[osmtype]:
                        self.dicosmtags[osmtype][osmid] = {items[1]: items[3]}
                    else:
                        self.dicosmtags[osmtype][osmid][items[1]] = items[3]
                    # If so, do we need to declare this osmid as a first catch,
                    # not one only brought with as a child
                    if input_tags and (
                        ((items[1], "") in input_tags[osmtype])
                        or ((items[1], items[3]) in input_tags[osmtype])
                    ):
                        self.dicosmfirst[osmtype].add(osmid)
            elif "</way" in items[0]:
                if not self.dicosmw[osmid]:
                    del self.dicosmw[osmid]
                    self.next_way_id += 1
                    if osmid in self.dicosmfirst["w"]:
                        self.dicosmfirst["w"].remove(osmid)
                    if osmid in self.dicosmtags["w"]:
                        del self.dicosmtags[osmtype][osmid]
            elif "</relation>" in items[0]:
                bad_rel = False
                for role, endpt in (
                    (r, e) for r in ["outer", "inner"] for e in dico_rel_check[r]
                ):
                    if len(dico_rel_check[role][endpt]) != 2:
                        bad_rel = True
                        break
                if bad_rel == True:
                    UI.lvprint(
                        2,
                        "Relation id=",
                        osmid,
                        "is ill formed and was not treated.",
                    )
                    del self.dicosmr[osmid]
                    del self.dicosmrorig[osmid]
                    del dico_rel_check
                    self.next_rel_id += 1
                    if osmid in self.dicosmfirst["r"]:
                        self.dicosmfirst["r"].remove(osmid)
                    if osmid in self.dicosmtags["r"]:
                        del self.dicosmtags["r"][osmid]
                    continue
                for role in ["outer", "inner"]:
                    while dico_rel_check[role]:
                        nodeids = []
                        endpt = next(iter(dico_rel_check[role]))
                        wayid = dico_rel_check[role][endpt][0]
                        endptinit = self.dicosmw[wayid][0]
                        endpt1 = endptinit
                        endpt2 = self.dicosmw[wayid][-1]
                        for nodeid in self.dicosmw[wayid][:-1]:
                            nodeids.append(nodeid)
                        while endpt2 != endptinit:
                            if dico_rel_check[role][endpt2][0] == wayid:
                                wayid = dico_rel_check[role][endpt2][1]
                            else:
                                wayid = dico_rel_check[role][endpt2][0]
                            endpt1 = endpt2
                            if self.dicosmw[wayid][0] == endpt1:
                                endpt2 = self.dicosmw[wayid][-1]
                                for nodeid in self.dicosmw[wayid][:-1]:
                                    nodeids.append(nodeid)
                            else:
                                endpt2 = self.dicosmw[wayid][0]
                                for nodeid in self.dicosmw[wayid][-1:0:-1]:
                                    nodeids.append(nodeid)
                            del dico_rel_check[role][endpt1]
                        nodeids.append(endptinit)
                        self.dicosmr[osmid][role].append(nodeids)
                        del dico_rel_check[role][endptinit]
                if target_tags == None:
                    for wayid in (
                        self.dicosmrorig[osmid]["outer"]
                        + self.dicosmrorig[osmid]["inner"]
                    ):
                        try:
                            self.dicosmfirst["w"].remove(wayid)
                        except:
                            pass
                if not self.dicosmr[osmid]["outer"]:
                    del self.dicosmr[osmid]
                    del self.dicosmrorig[osmid]
                    self.next_rel_id += 1
                    if osmid in self.dicosmfirst["r"]:
                        self.dicosmfirst["r"].remove(osmid)
                    if osmid in self.dicosmtags["r"]:
                        del self.dicosmtags["r"][osmid]
                del dico_rel_check
            elif "</osm>" in items[0]:
                normal_exit = True
        pfile.close()
        if not normal_exit:
            UI.lvprint(
                0,
                "ERROR: OSM overpass server answer was corrupted ",
                "(no ending </OSM> tag)",
            )
            return 0
        UI.vprint(
            2,
            "      A total of "
            + str(len(self.dicosmn) - initnodes)
            + " new node(s), "
            + str(len(self.dicosmfirst["w"]) - initways)
            + " new ways and "
            + str(len(self.dicosmfirst["r"]) - initrels)
            + " new relation(s).",
        )
        return 1

    def write_to_file(self, filename):
        try:
            if filename[-4:] == ".bz2":
                fout = bz2.open(filename, "wt", encoding="utf-8")
            else:
                fout = open(filename, "w", encoding="utf-8")
        except:
            UI.vprint(1, "    Could not open", filename, "for writing.")
            return 0
        fout.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" '
            + 'generator="Ortho4XP">\n'
        )
        if not len(self.dicosmfirst["n"]):
            for nodeid, (lonp, latp) in self.dicosmn.items():
                fout.write(
                    '  <node id="'
                    + str(nodeid)
                    + '" lat="'
                    + "{:.7f}".format(latp)
                    + '" lon="'
                    + "{:.7f}".format(lonp)
                    + '" version="1"/>\n'
                )
        else:
            for nodeid, (lonp, latp) in self.dicosmn.items():
                if nodeid not in self.dicosmtags["n"]:
                    fout.write(
                        '  <node id="'
                        + str(nodeid)
                        + '" lat="'
                        + "{:.7f}".format(latp)
                        + '" lon="'
                        + "{:.7f}".format(lonp)
                        + '" version="1"/>\n'
                    )
                else:
                    fout.write(
                        '  <node id="'
                        + str(nodeid)
                        + '" lat="'
                        + "{:.7f}".format(latp)
                        + '" lon="'
                        + "{:.7f}".format(lonp)
                        + '" version="1">\n'
                    )
                    for tag in self.dicosmtags["n"][nodeid]:
                        fout.write(
                            '    <tag k="'
                            + tag
                            + '" v="'
                            + self.dicosmtags["n"][nodeid][tag]
                            + '"/>\n'
                        )
                    fout.write("  </node>\n")
        for wayid in tuple(self.dicosmfirst["w"]) + tuple(
            set(self.dicosmw).difference(self.dicosmfirst["w"])
        ):
            fout.write('  <way id="' + str(wayid) + '" version="1">\n')
            for nodeid in self.dicosmw[wayid]:
                fout.write('    <nd ref="' + str(nodeid) + '"/>\n')
            for tag in (
                self.dicosmtags["w"][wayid] if wayid in self.dicosmtags["w"] else []
            ):
                fout.write(
                    '    <tag k="'
                    + tag
                    + '" v="'
                    + self.dicosmtags["w"][wayid][tag]
                    + '"/>\n'
                )
            fout.write("  </way>\n")
        for relid in tuple(self.dicosmfirst["r"]) + tuple(
            set(self.dicosmrorig).difference(self.dicosmfirst["r"])
        ):
            fout.write('  <relation id="' + str(relid) + '" version="1">\n')
            for wayid in self.dicosmrorig[relid]["outer"]:
                fout.write(
                    '    <member type="way" ref="' + str(wayid) + '" role="outer"/>\n'
                )
            for wayid in self.dicosmrorig[relid]["inner"]:
                fout.write(
                    '    <member type="way" ref="' + str(wayid) + '" role="inner"/>\n'
                )
            for tag in (
                self.dicosmtags["r"][relid] if relid in self.dicosmtags["r"] else []
            ):
                fout.write(
                    '    <tag k="'
                    + tag
                    + '" v="'
                    + self.dicosmtags["r"][relid][tag]
                    + '"/>\n'
                )
            fout.write("  </relation>\n")
        fout.write("</osm>")
        fout.close()
        return 1


def OSM_queries_to_OSM_layer(
    queries,
    osm_layer,
    lat,
    lon,
    tags_of_interest=[],
    cached_suffix="",
):
    # this one is a bit complicated by a few checks of existing cached data
    # which had different filenames is versions prior to 1.30
    target_tags = {"n": [], "w": [], "r": []}
    input_tags = {"n": [], "w": [], "r": []}
    for query in queries:
        for tag in [query] if isinstance(query, str) else query:
            items = tag.split('"')
            osm_type = items[0][0]
            try:
                target_tags[osm_type].append((items[1], items[3]))
                input_tags[osm_type].append((items[1], items[3]))
            except:
                target_tags[osm_type].append((items[1], ""))
                input_tags[osm_type].append((items[1], ""))
            for tag in tags_of_interest:
                if isinstance(tag, str):
                    if (tag, "") not in target_tags[osm_type]:
                        target_tags[osm_type].append((tag, ""))
                else:
                    if tag not in target_tags[osm_type]:
                        target_tags[osm_type].append(tag)
    cached_data_filename = FNAMES.osm_cached(lat, lon, cached_suffix)
    if cached_suffix and os.path.isfile(cached_data_filename):
        UI.vprint(1, "    * Recycling OSM data from", cached_data_filename)
        return osm_layer.update_dicosm(cached_data_filename, input_tags, target_tags)
    # Recycle per-query cached files from the pre-1.30 cache layout when
    # present, and collect every remaining statement so they can all be
    # downloaded in ONE batched Overpass request (see build_overpass_query
    # for why a single union request is preferable to one per statement).
    statements_to_download = []
    for query in queries:
        # look first for cached data (old scheme)
        if isinstance(query, str):
            old_cached_data_filename = FNAMES.osm_old_cached(lat, lon, query)
            if os.path.isfile(old_cached_data_filename):
                UI.vprint(1, "    * Recycling OSM data for", query)
                osm_layer.update_dicosm(
                    old_cached_data_filename, input_tags, target_tags
                )
                continue
            statements_to_download.append(query)
        else:
            statements_to_download.extend(query)
    if statements_to_download:
        UI.vprint(
            1,
            "    * Downloading OSM data for",
            ", ".join(statements_to_download),
        )
        response = get_overpass_data(
            statements_to_download, (lat, lon, lat + 1, lon + 1),
            request_description=cached_suffix,
        )
        if UI.red_flag:
            return 0
        if not response:
            UI.logprint(
                "No valid answer for",
                ", ".join(statements_to_download),
                "after",
                max_osm_tentatives,
                ", skipping it.",
            )
            UI.vprint(
                1,
                "      No valid answer after",
                max_osm_tentatives,
                ", skipping it.",
            )
            return 0
        osm_layer.update_dicosm(response, input_tags, target_tags)
    if cached_suffix:
        osm_layer.write_to_file(cached_data_filename)
    return 1


def OSM_query_to_OSM_layer(
    query,
    bbox,
    osm_layer,
    tags_of_interest=[],
    cached_file_name="",
):
    # this one is simpler and does not depend on the notion of tile
    target_tags = {"n": [], "w": [], "r": []}
    input_tags = {"n": [], "w": [], "r": []}
    for tag in [query] if isinstance(query, str) else query:
        items = tag.split('"')
        osm_type = items[0][0]
        try:
            target_tags[osm_type].append((items[1], items[3]))
            input_tags[osm_type].append((items[1], items[3]))
        except:
            target_tags[osm_type].append((items[1], ""))
            input_tags[osm_type].append((items[1], ""))
        for tag in tags_of_interest:
            if isinstance(tag, str):
                target_tags[osm_type].append((tag, ""))
            else:
                target_tags[osm_type].append(tag)
    if cached_file_name and os.path.isfile(cached_file_name):
        UI.vprint(1, "    * Recycling OSM data from", cached_file_name)
        osm_layer.update_dicosm(cached_file_name, input_tags, target_tags)
    else:
        response = get_overpass_data(query, bbox)
        if UI.red_flag:
            return 0
        if not response:
            UI.lvprint(
                1,
                "      No valid answer for",
                query,
                "after",
                max_osm_tentatives,
                ", skipping it.",
            )
            return 0
        osm_layer.update_dicosm(response, input_tags, target_tags)
        if cached_file_name:
            osm_layer.write_to_file(cached_file_name)
    return 1


# A single persistent HTTP session gives connection keep-alive: consecutive
# requests to the same server reuse one TCP/TLS connection instead of paying
# a new handshake each time, which is both faster and gentler on the public
# Overpass servers.
_http_session = None


def _get_http_session() -> requests.Session:
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        _http_session.headers.update(
            {
                "User-Agent": f"Ortho4XP/{O4XP_VERSION} "
                "(https://github.com/shred86/Ortho4XP)"
            }
        )
    return _http_session


def build_overpass_query(query_statements, bounding_box) -> str:
    """Assemble the complete Overpass QL text for one request.

    ``query_statements`` is a single Overpass statement (string), e.g.
    'way["highway"="motorway"]', or an iterable of statements.  All
    statements are placed in one union block so the server answers them
    in a SINGLE transaction: each request an Overpass server receives
    costs it a scheduling slot regardless of size, so one union query is
    much cheaper for the server (and far less likely to be rate-limited)
    than one request per statement.  It is also less data overall: the
    recurse-down (._;>>;) which pulls the child nodes of every matched
    way/relation runs once over the union, so nodes shared between
    statements (e.g. an intersection between a primary and a secondary
    road) are only downloaded once.
    """
    if isinstance(query_statements, str):
        query_statements = (query_statements,)
    bounding_box_filter = str(bounding_box) if bounding_box else ""
    union_of_statements = "".join(
        statement + bounding_box_filter + ";" for statement in query_statements
    )
    return (
        f"[out:xml][timeout:{overpass_query_timeout_seconds}];"
        f"({union_of_statements});(._;>>;);out meta;"
    )


status_probe_timeout_seconds = 5


def _parse_overpass_status_text(status_text: str) -> dict:
    """Extract slot availability from an Overpass /api/status answer.

    The status page is plain text of the form::

        Connected as: 1256987296
        Current time: 2026-07-03T23:40:01Z
        Rate limit: 6
        5 slots available now.
        Slot available after: 2026-07-03T23:40:20Z, in 19 seconds.
        Currently running queries (pid, space limit, time limit, ...):

    "Rate limit: 0" means the server does not rate-limit at all.  When
    every slot is busy the "slots available now" line is absent and only
    "Slot available after" lines remain.
    """
    slots_match = re.search(r"(\d+) slots? available now", status_text)
    slots_available_now = int(slots_match.group(1)) if slots_match else 0
    rate_limit_match = re.search(r"Rate limit: (\d+)", status_text)
    if rate_limit_match and int(rate_limit_match.group(1)) == 0:
        slots_available_now = max(slots_available_now, 1)
    slot_wait_matches = re.findall(r"in (-?\d+) seconds", status_text)
    if slots_available_now:
        seconds_until_next_free_slot = 0.0
    elif slot_wait_matches:
        seconds_until_next_free_slot = max(
            0.0, min(float(seconds) for seconds in slot_wait_matches)
        )
    else:
        seconds_until_next_free_slot = float("inf")
    return {
        "slots_available_now": slots_available_now,
        "seconds_until_next_free_slot": seconds_until_next_free_slot,
    }


def _read_overpass_server_status(server_key: str):
    """Probe one server's /api/status endpoint.

    Returns the parsed availability report augmented with the probe's
    round-trip time, or None when the server is unreachable or does not
    expose a standard status endpoint.  The probe is nearly free for the
    server, unlike a real query which costs it a scheduling slot and
    actual computation.
    """
    interpreter_url = overpass_servers[server_key].rstrip("/")
    if not interpreter_url.endswith("/interpreter"):
        return None
    status_url = interpreter_url.rsplit("/", 1)[0] + "/status"
    probe_started_at = time.time()
    try:
        response = _get_http_session().get(
            status_url,
            timeout=(status_probe_timeout_seconds, status_probe_timeout_seconds),
        )
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    availability_report = _parse_overpass_status_text(response.text)
    availability_report["probe_round_trip_seconds"] = (
        time.time() - probe_started_at
    )
    return availability_report


def _select_most_available_server_key(candidate_keys) -> str:
    """Probe every candidate server's status in parallel and pick the
    most available one: a server with a free slot for our IP (fastest
    probe answer wins), else the one whose next slot frees up soonest.
    Falls back to a random pick when no candidate answers its probe.
    """
    with ThreadPoolExecutor(max_workers=len(candidate_keys)) as executor:
        availability_by_key = dict(
            zip(
                candidate_keys,
                executor.map(_read_overpass_server_status, candidate_keys),
            )
        )
    UI.vprint(
        2,
        "      OSM server availability:",
        ", ".join(
            f"{key}: "
            + (
                f"{report['slots_available_now']} slot(s) now "
                f"({report['probe_round_trip_seconds']:.2f}s)"
                if report and report["slots_available_now"]
                else f"next slot in {report['seconds_until_next_free_slot']:.0f}s"
                if report
                else "no status answer"
            )
            for key, report in availability_by_key.items()
        ),
    )
    keys_with_free_slot = [
        key
        for key, report in availability_by_key.items()
        if report and report["slots_available_now"]
    ]
    if keys_with_free_slot:
        return min(
            keys_with_free_slot,
            key=lambda key: availability_by_key[key][
                "probe_round_trip_seconds"
            ],
        )
    reachable_keys = [
        key for key, report in availability_by_key.items() if report
    ]
    if reachable_keys:
        return min(
            reachable_keys,
            key=lambda key: availability_by_key[key][
                "seconds_until_next_free_slot"
            ],
        )
    return random.choice(list(candidate_keys))


def _select_overpass_server_key(server_keys, failed_server_key=None) -> str:
    """Choose which Overpass server the next request attempt goes to.

    A pinned choice (overpass_server_choice naming an entry from
    overpass_servers.txt) is always honoured.  In "random" mode the
    selection is sticky: keep using the server that last answered
    successfully — stickiness preserves the HTTP keep-alive connection
    and the server-side rate-limit slot we already hold.  Only when
    there is no proven-good server (first download of the session, or
    right after a failed attempt) are the candidates' status endpoints
    probed to find the most available one.
    """
    if overpass_server_choice in server_keys:
        return overpass_server_choice
    sticky_server_key = getattr(
        get_overpass_data, "last_successful_server_key", None
    )
    candidate_keys = [key for key in server_keys if key != failed_server_key]
    if not candidate_keys:
        candidate_keys = server_keys
    if sticky_server_key in candidate_keys:
        return sticky_server_key
    if len(candidate_keys) == 1:
        return candidate_keys[0]
    return _select_most_available_server_key(candidate_keys)


def _describe_overpass_response_problem(response):
    """Return a short description of what is wrong with an Overpass
    answer, or None when the answer is complete and usable."""
    if response.status_code != 200:
        return f"rejected our query (HTTP {response.status_code})"
    content = response.content
    if b"</osm>" not in content[-10:] and b"</OSM>" not in content[-10:]:
        return "sent a corrupted answer (no closing </osm> tag in answer)"
    if len(content) <= 1000 and b"error" in content:
        return "sent us an error code (data too big ?)"
    # A syntactically complete answer may still carry a <remark> trailer
    # when the server had to abort the query midway (runtime timeout,
    # memory exhaustion); accepting it would silently truncate the data.
    response_tail = content[-2048:]
    if b"<remark" in response_tail and (
        b"error" in response_tail or b"timed out" in response_tail
    ):
        return "aborted the query server-side (runtime timeout ?)"
    return None


# How often to reassure the user that a slow request is still alive.
progress_update_interval_seconds = 10


def _post_overpass_query_reporting_progress(server_key, overpass_query,
                                            request_label=""):
    """Send one Overpass request, reporting progress while it runs.

    The HTTP POST itself happens in a helper thread so this thread can
    print a reassurance line every few seconds — a busy server may
    legitimately spend minutes computing before the first byte arrives,
    and a silent console reads as a crash — and honour the GUI stop
    button mid-request.  Returns the requests.Response, or None when
    the user interrupted the wait (the helper thread is then abandoned;
    it ends on its own once the server answers or the timeout fires).
    Network failures raise requests.RequestException exactly as a
    direct requests call would.
    """
    request_outcome = {}

    def send_request():
        try:
            # POST keeps the query out of the URL: no length limit and
            # no characters for intermediaries to mangle, as recommended
            # by the Overpass API documentation for generated queries.
            request_outcome["response"] = _get_http_session().post(
                overpass_servers[server_key],
                data={"data": overpass_query},
                timeout=(
                    http_connect_timeout_seconds,
                    http_read_timeout_seconds,
                ),
            )
        except Exception as request_error:
            request_outcome["error"] = request_error

    request_thread = threading.Thread(target=send_request, daemon=True)
    request_thread.start()
    seconds_waited = 0
    while True:
        request_thread.join(timeout=progress_update_interval_seconds)
        if not request_thread.is_alive():
            break
        seconds_waited += progress_update_interval_seconds
        if UI.red_flag:
            return None
        UI.vprint(
            1,
            f"      OSM server {server_key}{request_label} is working on "
            f"our request ({seconds_waited}s), waiting for the answer...",
        )
    if "error" in request_outcome:
        raise request_outcome["error"]
    return request_outcome["response"]


def get_overpass_data(query, bbox, request_description="") -> bytes:
    """Fetch data for one or more Overpass statements in one transaction.

    ``query`` is a single Overpass statement or an iterable of statements;
    every statement is combined into one union request by
    build_overpass_query, so callers should pass ALL the statements they
    need at once rather than calling this once per statement.  Returns the
    raw XML answer as bytes, or 0 after max_osm_tentatives failures.

    ``request_description`` (e.g. the layer name "big_roads") is woven
    into every console line about this request, so that when several
    downloads interleave in the log — the background prefetch runs while
    other work prints — each line is attributable to its request.
    """
    if not overpass_servers:
        UI.lvprint(1, "No overpass servers configured. Check overpass_servers.txt.")
        return 0
    server_keys = list(overpass_servers.keys())
    if (
        overpass_server_choice != "random"
        and overpass_server_choice not in server_keys
    ):
        UI.lvprint(
            1,
            "Selected overpass server not found in overpass_servers.txt, using:",
            server_keys[0],
        )
    overpass_query = build_overpass_query(query, bbox)
    request_label = f" ({request_description})" if request_description else ""
    failed_server_key = None
    for tentative in range(1, max_osm_tentatives + 1):
        current_server_key = _select_overpass_server_key(
            server_keys, failed_server_key
        )
        # Announce the attempt BEFORE sending it: a busy server can hold
        # the connection open for minutes before failing, and without
        # this line the console would show no sign of life until then.
        UI.vprint(
            1,
            f"      Querying OSM server {current_server_key}{request_label} "
            f"(attempt {tentative}/{max_osm_tentatives})...",
        )
        UI.vprint(3, overpass_query)
        wait_seconds = 2**tentative
        try:
            response = _post_overpass_query_reporting_progress(
                current_server_key, overpass_query, request_label
            )
            if response is None:
                # The user interrupted the build while we were waiting.
                return 0
            problem_description = _describe_overpass_response_problem(response)
            if problem_description is None:
                get_overpass_data.last_successful_server_key = current_server_key
                return response.content
            if response.status_code == 429:
                # 429 is the overpass software rate limiting us; it tells
                # us in the Retry-After header how long to back off.  The
                # header may also be an HTTP-date (or absent), so parse
                # defensively, and cap the honoured value: the next
                # attempt rotates to a DIFFERENT server, so serving one
                # server's full rate-limit penalty would stall the build
                # for nothing.
                try:
                    retry_after_seconds = int(
                        response.headers.get("Retry-After", 0)
                    )
                except ValueError:
                    retry_after_seconds = 0
                wait_seconds = max(
                    min(retry_after_seconds, 120), wait_seconds
                )
            UI.vprint(
                1,
                f"      OSM server {current_server_key}{request_label} "
                f"{problem_description}, "
                f"new tentative in {wait_seconds} sec...",
            )
        except requests.RequestException:
            UI.vprint(
                1,
                f"      OSM server {current_server_key}{request_label} "
                f"was too busy, new tentative in {wait_seconds} sec...",
            )
        failed_server_key = current_server_key
        # Sleep in one-second slices so the GUI stop button stays
        # responsive during a long backoff wait.
        for _ in range(wait_seconds):
            if UI.red_flag:
                return 0
            time.sleep(1)
    return 0


def OSM_to_MultiLineString(osm_layer, lat, lon, tags_for_exclusion=set(), filter=None):
    multiline = []
    multiline_reject = []
    todo = len(osm_layer.dicosmfirst["w"])
    step = int(todo / 100) + 1
    done = 0
    filtered_segs = 0
    for wayid in osm_layer.dicosmfirst["w"]:
        if done % step == 0:
            UI.progress_bar(1, int(100 * done / todo))
        if (
            tags_for_exclusion
            and wayid in osm_layer.dicosmtags["w"]
            and not set(osm_layer.dicosmtags["w"][wayid].keys()).isdisjoint(
                tags_for_exclusion
            )
        ):
            done += 1
            continue
        way = numpy.round(
            numpy.array(
                [osm_layer.dicosmn[nodeid] for nodeid in osm_layer.dicosmw[wayid]],
                dtype=numpy.float64,
            )
            - numpy.array([[lon, lat]], dtype=numpy.float64),
            7,
        )
        if filter and not filter(way, filtered_segs):
            try:
                multiline_reject.append(geometry.LineString(way))
            except:
                pass
            done += 1
            continue
        try:
            multiline.append(geometry.LineString(way))
            filtered_segs += len(way)
        except:
            pass
        done += 1
    UI.progress_bar(1, 100)
    if not filter:
        return geometry.MultiLineString(multiline)
    else:
        UI.vprint(2, "      Number of filtered segs :", filtered_segs)
        return (
            geometry.MultiLineString(multiline),
            geometry.MultiLineString(multiline_reject),
        )


def OSM_to_MultiPolygon(osm_layer, lat, lon, filter=None):
    multilist = []
    excludelist = []
    todo = len(osm_layer.dicosmfirst["w"]) + len(osm_layer.dicosmfirst["r"])
    step = int(todo / 100) + 1
    done = 0
    for wayid in osm_layer.dicosmfirst["w"]:
        if done % step == 0:
            UI.progress_bar(1, int(100 * done / todo))
        if osm_layer.dicosmw[wayid][0] != osm_layer.dicosmw[wayid][-1]:
            UI.logprint(
                "Non closed way starting at",
                osm_layer.dicosmn[osm_layer.dicosmw[wayid][0]],
                ", skipped.",
            )
            done += 1
            continue
        way = numpy.round(
            numpy.array(
                [osm_layer.dicosmn[nodeid] for nodeid in osm_layer.dicosmw[wayid]],
                dtype=numpy.float64,
            )
            - numpy.array([[lon, lat]], dtype=numpy.float64),
            7,
        )
        try:
            pol = geometry.Polygon(way)
            if not pol.area:
                continue
            if not pol.is_valid:
                UI.logprint(
                    "Invalid OSM way starting at",
                    osm_layer.dicosmn[osm_layer.dicosmw[wayid][0]],
                    ", skipped.",
                )
                done += 1
                continue
        except Exception as e:
            UI.vprint(2, e)
            done += 1
            continue
        if filter and filter(pol, wayid, osm_layer.dicosmtags["w"]):
            excludelist.append(pol)
        else:
            multilist.append(pol)
        done += 1
    for relid in osm_layer.dicosmfirst["r"]:
        if done % step == 0:
            UI.progress_bar(1, int(100 * done / todo))
        try:
            multiout = [
                geometry.Polygon(
                    numpy.round(
                        numpy.array(
                            [osm_layer.dicosmn[nodeid] for nodeid in nodelist],
                            dtype=numpy.float64,
                        )
                        - numpy.array([lon, lat], dtype=numpy.float64),
                        7,
                    )
                )
                for nodelist in osm_layer.dicosmr[relid]["outer"]
            ]
            multiout = ops.unary_union([geom for geom in multiout if geom.is_valid])
            multiin = [
                geometry.Polygon(
                    numpy.round(
                        numpy.array(
                            [osm_layer.dicosmn[nodeid] for nodeid in nodelist],
                            dtype=numpy.float64,
                        )
                        - numpy.array([lon, lat], dtype=numpy.float64),
                        7,
                    )
                )
                for nodelist in osm_layer.dicosmr[relid]["inner"]
            ]
            multiin = ops.unary_union([geom for geom in multiin if geom.is_valid])
        except Exception as e:
            UI.logprint(e)
            done += 1
            continue
        multipol = multiout.difference(multiin)
        if filter and filter(multipol, relid, osm_layer.dicosmtags["r"]):
            targetlist = excludelist
        else:
            targetlist = multilist
        for pol in (
            multipol.geoms
            if ("Multi" in multipol.geom_type or "Collection" in multipol.geom_type)
            else [multipol]
        ):
            if not pol.area:
                done += 1
                continue
            if not pol.is_valid:
                UI.logprint(
                    "Relation",
                    relid,
                    "contains an invalid polygon which was discarded",
                )
                done += 1
                continue
            targetlist.append(pol)
        done += 1
    if filter:
        ret_val = (
            geometry.MultiPolygon(multilist),
            geometry.MultiPolygon(excludelist),
        )
        UI.vprint(
            2,
            "    Total number of geometries:",
            len(ret_val[0].geoms),
            len(ret_val[1].geoms),
        )
    else:
        ret_val = geometry.MultiPolygon(multilist)
        UI.vprint(2, "    Total number of geometries:", len(ret_val.geoms))
    UI.progress_bar(1, 100)
    return ret_val
