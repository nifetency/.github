import os, requests, json, sys, time

TOKEN = os.environ["GH_TOKEN"]
ORG = "nifetency"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}
GQL_HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

PROJECT_ID = "PVT_kwDOBAALrM4BeIJY"
REPO_FIELD = "PVTF_lADOBAALrM4BeIJYzhYkqME"
CRIT_FIELD = "PVTF_lADOBAALrM4BeIJYzhYkqJ8"
HIGH_FIELD = "PVTF_lADOBAALrM4BeIJYzhYkqKA"
MED_FIELD = "PVTF_lADOBAALrM4BeIJYzhYkqKE"
LOW_FIELD = "PVTF_lADOBAALrM4BeIJYzhYkqKI"
TOTAL_FIELD = "PVTF_lADOBAALrM4BeIJYzhYkqKM"


def get_active_repos():
    repos = []
    page = 1
    while True:
        r = requests.get(f"https://api.github.com/orgs/{ORG}/repos",
                          headers=HEADERS, params={"per_page": 100, "page": page, "type": "all"})
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        repos.extend([x["name"] for x in batch if not x.get("archived")])
        page += 1
    return repos


def get_open_alerts(repo):
    alerts = []
    url = f"https://api.github.com/repos/{ORG}/{repo}/dependabot/alerts"
    params = {"per_page": 100, "state": "open"}
    while url:
        r = requests.get(url, headers=HEADERS, params=params)
        if r.status_code != 200:
            return None
        alerts.extend(r.json())
        next_url = None
        if "Link" in r.headers:
            for part in r.headers["Link"].split(","):
                if 'rel="next"' in part:
                    next_url = part.split(";")[0].strip().strip("<>")
        url, params = next_url, {}
    return alerts


def gql(query, variables):
    r = requests.post("https://api.github.com/graphql", headers=GQL_HEADERS, json={"query": query, "variables": variables})
    return r.json()


def get_existing_items():
    items = {}
    cursor = None
    query = """
    query($projectId: ID!, $cursor: String) {
      node(id: $projectId) {
        ... on ProjectV2 {
          items(first: 100, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              id
              repoField: fieldValueByName(name: "Repository name") { ... on ProjectV2ItemFieldTextValue { text } }
            }
          }
        }
      }
    }
    """
    while True:
        resp = gql(query, {"projectId": PROJECT_ID, "cursor": cursor})
        page = resp["data"]["node"]["items"]
        for node in page["nodes"]:
            repo_name = node["repoField"]["text"] if node["repoField"] else None
            if repo_name:
                items[repo_name] = node["id"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return items


def set_text(item_id, field_id, value):
    gql("""mutation($p:ID!,$i:ID!,$f:ID!,$v:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{text:$v}}){projectV2Item{id}}}""",
        {"p": PROJECT_ID, "i": item_id, "f": field_id, "v": value})


def set_num(item_id, field_id, value):
    gql("""mutation($p:ID!,$i:ID!,$f:ID!,$v:Float!){updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{number:$v}}){projectV2Item{id}}}""",
        {"p": PROJECT_ID, "i": item_id, "f": field_id, "v": float(value)})


def create_item(repo):
    resp = gql("""mutation($p:ID!,$t:String!,$b:String!){addProjectV2DraftIssue(input:{projectId:$p,title:$t,body:$b}){projectItem{id}}}""",
                {"p": PROJECT_ID, "t": repo, "b": f"Open Dependabot alerts for {repo}.\nhttps://github.com/{ORG}/{repo}/security/dependabot"})
    return resp["data"]["addProjectV2DraftIssue"]["projectItem"]["id"]


def main():
    print("Fetching active repos...", file=sys.stderr)
    repos = get_active_repos()
    print(f"{len(repos)} active repos", file=sys.stderr)

    print("Fetching existing project items...", file=sys.stderr)
    existing = get_existing_items()
    print(f"{len(existing)} existing items", file=sys.stderr)

    seen_with_alerts = set()

    for repo in repos:
        alerts = get_open_alerts(repo)
        if alerts is None:
            continue
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for a in alerts:
            sev = a["security_advisory"]["severity"]
            counts[sev] = counts.get(sev, 0) + 1
        total = len(alerts)

        if total == 0:
            if repo in existing:
                item_id = existing[repo]
                set_num(item_id, CRIT_FIELD, 0)
                set_num(item_id, HIGH_FIELD, 0)
                set_num(item_id, MED_FIELD, 0)
                set_num(item_id, LOW_FIELD, 0)
                set_num(item_id, TOTAL_FIELD, 0)
                print(f"{repo}: cleared (0 alerts now)", file=sys.stderr)
            continue

        seen_with_alerts.add(repo)
        if repo in existing:
            item_id = existing[repo]
        else:
            item_id = create_item(repo)
            set_text(item_id, REPO_FIELD, repo)
            print(f"{repo}: created new item", file=sys.stderr)

        set_num(item_id, CRIT_FIELD, counts["critical"])
        set_num(item_id, HIGH_FIELD, counts["high"])
        set_num(item_id, MED_FIELD, counts["medium"])
        set_num(item_id, LOW_FIELD, counts["low"])
        set_num(item_id, TOTAL_FIELD, total)
        print(f"{repo}: C{counts['critical']}/H{counts['high']}/M{counts['medium']}/L{counts['low']}", file=sys.stderr)
        time.sleep(0.05)

    print("Sync complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
