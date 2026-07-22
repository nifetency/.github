import os, requests, json, sys, time

TOKEN = os.environ["GH_TOKEN"]
ORG = "nifetency"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}
GQL_HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

PROJECT_ID = "PVT_kwDOBAALrM4BeIcn"
REPO_FIELD = "PVTF_lADOBAALrM4BeIcnzhYk7Tc"
STATUS_FIELD = "PVTSSF_lADOBAALrM4BeIcnzhYk7Tg"
DATE_FIELD = "PVTF_lADOBAALrM4BeIcnzhYk7Tk"
WORKFLOW_FIELD = "PVTF_lADOBAALrM4BeIcnzhYk7Ug"

STATUS_OPTIONS = {
    "success": "e23e68d2",
    "failure": "9c62e0a8",
    "in_progress": "bf3bccc9",
    "cancelled": "fe0f722a",
    "no_runs": "0b6c2bf5",
}


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


def get_latest_run(repo):
    r = requests.get(f"https://api.github.com/repos/{ORG}/{repo}/actions/runs",
                      headers=HEADERS, params={"per_page": 1})
    if r.status_code != 200:
        return None
    runs = r.json().get("workflow_runs", [])
    if not runs:
        return None
    run = runs[0]
    status = run["conclusion"] if run["conclusion"] else run["status"]
    return {"status": status, "name": run["name"], "date": run["created_at"][:10]}


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


def set_date(item_id, field_id, value):
    gql("""mutation($p:ID!,$i:ID!,$f:ID!,$v:Date!){updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{date:$v}}){projectV2Item{id}}}""",
        {"p": PROJECT_ID, "i": item_id, "f": field_id, "v": value})


def set_select(item_id, field_id, option_id):
    gql("""mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){projectV2Item{id}}}""",
        {"p": PROJECT_ID, "i": item_id, "f": field_id, "o": option_id})


def create_item(repo):
    resp = gql("""mutation($p:ID!,$t:String!,$b:String!){addProjectV2DraftIssue(input:{projectId:$p,title:$t,body:$b}){projectItem{id}}}""",
                {"p": PROJECT_ID, "t": repo, "b": f"CI status for {repo}.\nhttps://github.com/{ORG}/{repo}/actions"})
    return resp["data"]["addProjectV2DraftIssue"]["projectItem"]["id"]


def main():
    print("Fetching active repos...", file=sys.stderr)
    repos = get_active_repos()
    print(f"{len(repos)} active repos", file=sys.stderr)

    print("Fetching existing project items...", file=sys.stderr)
    existing = get_existing_items()
    print(f"{len(existing)} existing items", file=sys.stderr)

    for repo in repos:
        run = get_latest_run(repo)
        if repo in existing:
            item_id = existing[repo]
        else:
            if run is None:
                continue  # don't create items for repos with no CI at all
            item_id = create_item(repo)
            set_text(item_id, REPO_FIELD, repo)
            print(f"{repo}: created new item", file=sys.stderr)

        if run is None:
            set_select(item_id, STATUS_FIELD, STATUS_OPTIONS["no_runs"])
            print(f"{repo}: no runs", file=sys.stderr)
            continue

        status_key = run["status"] if run["status"] in STATUS_OPTIONS else "no_runs"
        set_select(item_id, STATUS_FIELD, STATUS_OPTIONS[status_key])
        set_date(item_id, DATE_FIELD, run["date"])
        set_text(item_id, WORKFLOW_FIELD, run["name"])
        print(f"{repo}: {status_key} ({run['name']}, {run['date']})", file=sys.stderr)
        time.sleep(0.05)

    print("Sync complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
