from datetime import date
import hashlib
import json

import pytest

from tma_app import user_account as user


def test_authorization_formula_and_permanent_machine_binding(monkeypatch):
    day=date(2026,10,23)
    assert user.authorization_code(day)==hashlib.sha256(b'20261023').hexdigest()
    monkeypatch.setattr(user,'machine_code',lambda:'MACHINE-A')
    user.login('实验员')
    record=user.activate(user.authorization_code(day).upper(),day=day)
    assert user.is_member(record) and user.is_member(user.load_account())
    assert not user.is_member(record,machine='MACHINE-B')
    # Validation on later launches uses the activation date, not today's code.
    original=user.authorization_code
    monkeypatch.setattr(user,'authorization_code',lambda day=None:original(day or date(2035,1,1)))
    assert user.is_member(user.load_account())
    user.login('新昵称')
    assert user.load_account()['nickname']=='新昵称' and user.is_member()


@pytest.mark.parametrize('code',['','wrong','汉'*64,hashlib.sha256(b'20261022').hexdigest()])
def test_invalid_authorization_preserves_previous_account(code):
    user.login('测试用户');before=user.account_path().read_bytes()
    with pytest.raises(ValueError):user.activate(code,day=date(2026,10,23))
    assert user.account_path().read_bytes()==before and not user.is_member()


def test_activation_requires_local_nickname():
    with pytest.raises(ValueError,match='登录'):user.activate(user.authorization_code())
    with pytest.raises(ValueError):user.login(' ')


def test_denied_primary_falls_back_without_altering_other_settings(tmp_path,monkeypatch):
    primary=user.account_path();portable=tmp_path/'portable/user.json'
    monkeypatch.setattr(user,'portable_path',lambda path:portable)
    original=user.write_json;attempts=[]
    def writer(path,data):
        attempts.append(path)
        if path==primary:raise PermissionError('fixture denied')
        return original(path,data)
    monkeypatch.setattr(user,'write_json',writer)
    user.login('缓存测试');user.activate(user.authorization_code())
    assert user.is_member() and not primary.exists() and portable.exists()
    assert attempts==[primary,portable,primary,portable]


def test_registry_mirror_restores_membership_without_old_package_files(monkeypatch):
    stored={}
    monkeypatch.setattr(user,'write_registry',lambda data:stored.update(data) or True)
    monkeypatch.setattr(user,'read_registry',lambda:dict(stored) if stored else None)
    user.login('长期用户');user.activate(user.authorization_code())
    user.account_path().unlink()
    assert user.is_member() and user.load_account()['nickname']=='长期用户'
    monkeypatch.setattr(user,'machine_code',lambda:'OTHER-MACHINE')
    assert not user.is_member()


def test_failed_storage_does_not_claim_activation(monkeypatch):
    user.login('原用户');before=user.account_path().read_bytes()
    def denied(*args):raise PermissionError('fixture denied')
    monkeypatch.setattr(user,'write_json',denied)
    with pytest.raises(PermissionError):user.activate(user.authorization_code())
    assert user.account_path().read_bytes()==before and not user.is_member()


def test_tampered_or_malformed_activation_is_not_valid(monkeypatch):
    monkeypatch.setattr(user,'machine_code',lambda:'MACHINE-A')
    record={'nickname':'测试','machine':'MACHINE-A','grant_day':'20261023','grant_hash':'汉'*64}
    assert not user.is_member(record)
    record.update(grant_hash=user.authorization_code(date(2026,10,23)),grant_day='not a date')
    assert not user.is_member(record)


def test_version_directory_change_preserves_fallback_membership(tmp_path,monkeypatch):
    from tma_app import ui_size
    monkeypatch.setattr(ui_size.sys,'frozen',True,raising=False)
    monkeypatch.setenv('ZZZHE_TMA_ACCOUNT_REGISTRY','0')
    monkeypatch.setattr(ui_size.sys,'executable',str(tmp_path/'dist-old/ZzzHe TMA Analysis/app.exe'))
    primary=user.account_path();original=user.write_json
    def denied(path,data):
        if path==primary:raise PermissionError('fixture read-only profile')
        return original(path,data)
    monkeypatch.setattr(user,'write_json',denied)
    user.login('更新保留');user.activate(user.authorization_code())
    stored=user.portable_path(primary)
    monkeypatch.setattr(ui_size.sys,'executable',str(tmp_path/'dist-new/ZzzHe TMA Analysis/app.exe'))
    assert user.portable_path(primary)==stored
    assert user.is_member() and user.load_account()['nickname']=='更新保留'
