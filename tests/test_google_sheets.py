import json
from pathlib import Path

import pytest

from delivery_assistant.backlog_models import BACKLOG_FIELDS, BACKLOG_HEADERS
from delivery_assistant import google_sheets as gs


def row(**changes):
    data={
        "request_id":"REQ-001", "category":"BI report change", "title":"Revenue policy",
        "description":"Exclude canceled orders from revenue.", "business_impact":"5", "priority":"A",
        "desired_by":"2026-11-18", "requester_team":"Digital Marketing", "requested_on":"2026-11-15",
        "ba_status":"Ready", "ba_notes":"Discussed and clarified.",
        "acceptance_criteria":"Revenue excludes canceled orders.", "effort":"S", "target_metric":"revenue",
        "ba_decision":"Pending", "planned_start":"", "planned_finish":"", "actual_start":"",
        "actual_finish":"", "delivery_reference":"",
    }
    data.update(changes)
    return [data[key] for key in BACKLOG_FIELDS]


def test_parse_exact_headers_trailing_blanks_and_reordered_columns():
    matrix=[BACKLOG_HEADERS,row()[:-4],[]]
    items=gs.parse_backlog_values(matrix)
    assert len(items)==1 and items[0].business_impact==5 and items[0].desired_by=="2026-11-18"
    reversed_items=gs.parse_backlog_values([list(reversed(BACKLOG_HEADERS)),list(reversed(row()))])
    assert reversed_items==items


@pytest.mark.parametrize("changes",[
    {"business_impact":"6"}, {"business_impact":True}, {"priority":"Urgent"},
    {"desired_by":"2026/11/18"}, {"desired_by":"2026-02-30"}, {"requested_on":"20261115"},
    {"description":""}, {"ba_status":"Approved automatically"},
])
def test_invalid_cells_are_bounded_without_echoing_values(changes):
    with pytest.raises(gs.GoogleSheetsError):
        gs.parse_backlog_values([BACKLOG_HEADERS,row(**changes)])


def test_duplicate_ids_headers_and_oversized_range_are_rejected():
    for matrix in [
        [BACKLOG_HEADERS,row(),row()],
        [[BACKLOG_HEADERS[0]]*20,row()],
        [BACKLOG_HEADERS]+[row(request_id=f"REQ-{n}") for n in range(198)],
    ]:
        with pytest.raises(gs.GoogleSheetsError):gs.parse_backlog_values(matrix)


def test_cells_are_data_and_not_executed_or_followed():
    formula='=HYPERLINK("https://example.invalid/never-requested", "request")'
    item=gs.parse_backlog_values([BACKLOG_HEADERS,row(description=formula)])[0]
    assert item.description==formula


def test_draft_ba_fields_remain_unknown_without_invented_business_ratings():
    item=gs.parse_backlog_values([BACKLOG_HEADERS,row(
        business_impact="",priority="",effort="",ba_status="",ba_decision="",acceptance_criteria="",
    )])[0]
    assert item.business_impact is None
    assert item.priority=="Unassigned"
    assert item.effort=="Unknown" and item.ba_status=="New" and item.ba_decision=="Pending"
    assert item.acceptance_criteria==""


def test_initial_request_needs_only_id_title_and_description():
    values={key:"" for key in BACKLOG_FIELDS}
    values.update(request_id="REQ-DRAFT",title="Discuss a new report",description="Oral consultation notes; BA review is pending.")
    item=gs.parse_backlog_values([BACKLOG_HEADERS,[values[key] for key in BACKLOG_FIELDS]])[0]
    assert item.request_id=="REQ-DRAFT" and item.business_impact is None
    assert item.priority=="Unassigned" and item.target_metric==""


class FakeResponse:
    def __init__(self,status=200,payload=None,raw=None):
        self.status_code=status
        self.raw=raw if raw is not None else json.dumps(payload or {"values":[BACKLOG_HEADERS,row()]}).encode()
        self.closed=False
    def iter_content(self,chunk_size):
        yield self.raw
    def close(self):self.closed=True


class FakeSession:
    def __init__(self,response):self.response=response;self.calls=[];self.closed=False
    def get(self,*args,**kwargs):self.calls.append((args,kwargs));return self.response
    def close(self):self.closed=True


def test_live_reader_uses_only_fixed_readonly_endpoint(monkeypatch,tmp_path):
    response=FakeResponse()
    session=FakeSession(response)
    marker=object()
    monkeypatch.setattr(gs,"_load_credentials",lambda root:marker)
    monkeypatch.setattr(gs,"_authorized_session",lambda creds:session)
    saved=[]
    monkeypatch.setattr(gs,"_save_credentials",lambda creds,root:saved.append(creds))
    items=gs.read_backlog(gs.EXPECTED_SHEET_ID,project_root=tmp_path)
    assert len(items)==1 and saved==[marker] and response.closed and session.closed
    args,kwargs=session.calls[0]
    assert args[0]==f"https://sheets.googleapis.com/v4/spreadsheets/{gs.EXPECTED_SHEET_ID}/values/Request%20backlog%21A3%3AT200"
    assert kwargs["params"]=={"majorDimension":"ROWS","valueRenderOption":"FORMATTED_VALUE"}
    assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
    assert kwargs["timeout"]==(10,30)


def test_unapproved_id_or_unbounded_range_stops_before_auth(monkeypatch):
    def forbidden_auth(root):raise AssertionError("Authentication should not be reached")
    monkeypatch.setattr(gs,"_load_credentials",forbidden_auth)
    for sheet,range_name in [("https://attacker.invalid",gs.DEFAULT_RANGE),(gs.EXPECTED_SHEET_ID,"Request backlog!A:T")]:
        with pytest.raises(gs.GoogleSheetsError):gs.read_backlog(sheet,range_name)


@pytest.mark.parametrize("status",[301,401,403,404,429,500])
def test_api_errors_never_echo_response_or_credentials(monkeypatch,status):
    response=FakeResponse(status=status,raw=b"secret-value-must-not-appear")
    session=FakeSession(response)
    monkeypatch.setattr(gs,"_load_credentials",lambda root:object())
    monkeypatch.setattr(gs,"_authorized_session",lambda creds:session)
    with pytest.raises(gs.GoogleSheetsError) as error:gs.read_backlog(gs.EXPECTED_SHEET_ID)
    assert "secret-value" not in str(error.value)
    assert response.closed and session.closed


def test_response_size_and_invalid_structure_rejected(monkeypatch):
    monkeypatch.setattr(gs,"_load_credentials",lambda root:object())
    for response in [FakeResponse(raw=b"x"*(gs.MAX_RESPONSE_BYTES+1)),FakeResponse(payload={"majorDimension":"COLUMNS","values":[]}),FakeResponse(raw=b"invalid-json")]:
        monkeypatch.setattr(gs,"_authorized_session",lambda creds,r=response:FakeSession(r))
        with pytest.raises(gs.GoogleSheetsError):gs.read_backlog(gs.EXPECTED_SHEET_ID)


def test_missing_setup_is_noninteractive(monkeypatch,tmp_path):
    assert gs.connection_status(tmp_path)["configured"] is False
    with pytest.raises(gs.GoogleSheetsError,match="not connected"):
        gs.read_backlog(gs.EXPECTED_SHEET_ID,project_root=tmp_path)
    with pytest.raises(gs.GoogleSheetsError,match="Desktop client"):
        gs.connect_google(tmp_path)


def token_info(**changes):
    info={"token":"synthetic-token-not-for-use","refresh_token":"synthetic-refresh-not-for-use",
          "token_uri":gs.TOKEN_URI,"client_id":"synthetic-test.apps.googleusercontent.com",
          "client_secret":"synthetic-client-not-for-use","scopes":list(gs.SCOPES)}
    info.update(changes)
    return info


@pytest.mark.parametrize("changes",[{"scopes":["https://www.googleapis.com/auth/spreadsheets"]},{"scopes":[{}]},{"token_uri":"https://attacker.invalid/token"},{"client_id":"bad-client"}])
def test_saved_token_scope_and_endpoint_are_validated(tmp_path,changes):
    folder=tmp_path/".secrets";folder.mkdir()
    (folder/"google_token.json").write_text(json.dumps(token_info(**changes)),encoding="utf-8")
    status=gs.connection_status(tmp_path)
    assert status["configured"] is False


def test_atomic_token_storage_stays_inside_secrets(tmp_path):
    class FakeCredentials:
        def to_json(self):return json.dumps(token_info())
    gs._save_credentials(FakeCredentials(),tmp_path)
    target=tmp_path/".secrets/google_token.json"
    assert json.loads(target.read_text(encoding="utf-8"))["scopes"]==list(gs.SCOPES)
    assert not list(target.parent.glob("*.tmp"))
    assert gs.connection_status(tmp_path)["configured"] is True


def test_unsafe_storage_path_is_denied(monkeypatch,tmp_path):
    original=Path.is_symlink
    monkeypatch.setattr(Path,"is_symlink",lambda path: path.name==".secrets" or original(path))
    with pytest.raises(gs.GoogleSheetsError):gs._secret_path(tmp_path,"google_token.json")


def test_web_or_redirected_oauth_clients_are_denied():
    for config in [{"web":{}},{"installed":{"token_uri":"https://attacker.invalid/token"}}]:
        with pytest.raises(gs.GoogleSheetsError):gs._validate_client_config(config)
