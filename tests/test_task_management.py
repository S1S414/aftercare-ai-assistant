import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
import test_assistant_routes as base
from aftercare_app.services import assistant as service
from aftercare_app.task_management import eligible


class ManagementTests(unittest.TestCase):
    setUp = base.AssistantRouteTests.setUp
    draft = base.AssistantRouteTests.draft

    def test_selected_groups_atomic_and_rechecked(self):
        old=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
        with patch('aftercare_app.services.assistant.now',return_value=old):
            a=self.draft(); b=self.draft()
        page=self.client.get('/assistant').get_data(as_text=True)
        self.assertIn('待确认且7天未修改：2条',page)
        body={'items':[{'id':a['id'],'version':1},{'id':b['id'],'version':1}],'confirmed':True}
        url='/api/assistant/cleanup/selected'
        self.assertEqual(self.client.post(url,json=body).status_code,403)
        service.edit_draft(self.db,self.actor,b['id'],1,'product','changed')
        self.assertEqual(self.client.post(url,json=body,headers=self.headers).status_code,409)
        self.assertIsNotNone(service.get_task(self.db,self.actor,a['id']))
        body['items']=body['items'][:1]
        self.assertEqual(self.client.post(url,json=body,headers=self.headers).json['data']['deleted'],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM assistant_events WHERE task_id=?',(a['id'],)).fetchone()[0],0)

    def test_delete_ownership_version_completed_and_csrf(self):
        task = self.draft()
        url = '/api/assistant/tasks/'+task['id']
        body = {'version':1,'confirmed':True}
        self.assertEqual(self.client.delete(url,json=body).status_code,403)
        self.assertEqual(self.client.delete(url,json={**body,'version':2},headers=self.headers).status_code,409)
        with self.client.session_transaction() as s: s['user_id']=self.other
        self.assertEqual(self.client.delete(url,json=body,headers=self.headers).status_code,404)
        with self.client.session_transaction() as s: s['user_id']=self.actor
        self.assertEqual(self.client.delete(url,json=body,headers=self.headers).status_code,200)
        self.assertEqual(self.db.execute('SELECT count(*) FROM assistant_events WHERE task_id=?',(task['id'],)).fetchone()[0],0)
        task = self.draft()
        service.confirm_task(self.db,self.actor,task['id'],1)
        self.assertEqual(self.client.delete('/api/assistant/tasks/'+task['id'],json=body,headers=self.headers).status_code,409)

    def old_cancelled(self):
        old = (datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
        with patch('aftercare_app.services.assistant.now',return_value=old):
            task=self.draft()
            return service.cancel_task(self.db,self.actor,task['id'],1)

    def test_cleanup_exact_preview_and_other_records_preserved(self):
        old=self.old_cancelled()
        draft=self.draft()
        preview=self.client.post('/api/assistant/cleanup/preview',json={},headers=self.headers).json['data']
        self.assertEqual([r['id'] for r in preview['rows']],[old['id']])
        later=self.old_cancelled()
        response=self.client.post('/api/assistant/cleanup/confirm',json={'token':preview['token'],'confirmed':True},headers=self.headers)
        self.assertEqual(response.json['data']['deleted'],1)
        for task in (draft,later): self.assertIsNotNone(service.get_task(self.db,self.actor,task['id']))

    def test_boundary_unknown_time_and_rollback(self):
        first=self.old_cancelled(); second=self.old_cancelled()
        cutoff=datetime.now(timezone.utc)-timedelta(days=7)
        self.db.execute("UPDATE assistant_events SET created_at=? WHERE task_id=? AND action='cancelled'",(cutoff.isoformat(),first['id']))
        self.assertFalse(eligible(self.db,first,cutoff))
        self.db.execute("UPDATE assistant_events SET created_at='bad' WHERE task_id=? AND action='cancelled'",(first['id'],))
        self.assertFalse(eligible(self.db,first,cutoff))
        preview=self.client.post('/api/assistant/cleanup/preview',json={},headers=self.headers).json['data']
        self.db.execute("CREATE TRIGGER refuse_task_delete BEFORE DELETE ON assistant_tasks BEGIN SELECT RAISE(ABORT,'test'); END")
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.client.post('/api/assistant/cleanup/confirm',json={'token':preview['token'],'confirmed':True},headers=self.headers)
        self.assertGreater(self.db.execute('SELECT count(*) FROM assistant_events WHERE task_id=?',(second['id'],)).fetchone()[0],0)

    def test_page_filters_pagination_and_escaping(self):
        for i in range(12): self.draft()
        response=self.client.get('/assistant?page=2&state=draft')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data.count(b'data-delete-task='),2)
        self.assertEqual(self.client.get('/assistant?state=invalid').status_code,400)
        self.assertNotIn(b'data-delete-task=',self.client.get('/assistant?order=999').data)

    def test_preview_tampering_and_state_change_rejected(self):
        task=self.old_cancelled()
        preview=self.client.post('/api/assistant/cleanup/preview',json={},headers=self.headers).json['data']
        self.assertEqual(self.client.post('/api/assistant/cleanup/confirm',json={'token':'bad','confirmed':True},headers=self.headers).status_code,409)
        self.db.execute("UPDATE assistant_tasks SET state='draft' WHERE id=?",(task['id'],))
        self.assertEqual(self.client.post('/api/assistant/cleanup/confirm',json={'token':preview['token'],'confirmed':True},headers=self.headers).status_code,409)
        self.assertIsNotNone(service.get_task(self.db,self.actor,task['id']))
