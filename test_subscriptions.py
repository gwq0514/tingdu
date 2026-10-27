import json
from pathlib import Path
from unittest.mock import patch
import app
import subscriptions
import tests as baseline
import unittest

class SubscriptionTests(unittest.TestCase):
    setUp=baseline.PipelineTests.setUp
    tearDown=baseline.PipelineTests.tearDown
    # Reuse the isolated engine storage fixture without inheriting unrelated tests below.
    def make_author_job(self):
        r=app.new('原始视频','https://www.bilibili.com/video/BVexample0001')
        r.update(status='done',text='原文',creator={'key':'bilibili:123','platform':'bilibili','id':'123','name':'测试作者','url':'https://space.bilibili.com/123/upload/video'})
        app.save(r);return r
    def subscribed(self):
        r=self.make_author_job();result=self.client.post('/api/subscriptions',json={'job_id':r['id']})
        self.assertEqual(result.status_code,200);return result.json()
    def page(self,start=0,count=30,more=False):
        return {'items':[{'id':f'BVtest{i:06d}','title':f'视频{i}','url':f'https://www.bilibili.com/video/BVtest{i:06d}','thumbnail':'','creator_key':'bilibili:123'} for i in range(start,start+count)],'cursor':str(start+count),'has_more':more,'total':count+start+(2 if more else 0)}
    def test_subscribe_idempotent_and_unsubscribe_preserves_resources(self):
        r=self.make_author_job()
        for _ in range(2):self.assertEqual(self.client.post('/api/subscriptions',json={'job_id':r['id']}).status_code,200)
        self.assertEqual(len(self.client.get('/api/subscriptions').json()),1)
        self.assertEqual(self.client.delete('/api/subscriptions/bilibili:123').status_code,200)
        self.assertEqual(self.client.get('/api/subscriptions').json(),[])
        self.assertEqual(app.read(r['id'])['text'],'原文')
    def test_ten_items_per_page_and_cached_pagination(self):
        self.subscribed()
        with patch('subscriptions.fetch_bilibili',side_effect=[self.page(more=True),self.page(30,2)]) as fetch:
            first=self.client.get('/api/subscriptions/bilibili:123/videos').json()
            second=self.client.get('/api/subscriptions/bilibili:123/videos?offset=10').json()
            third=self.client.get('/api/subscriptions/bilibili:123/videos?offset=20').json()
            self.assertEqual([len(p['items']) for p in (first,second,third)],[10,10,10])
            self.assertEqual(fetch.call_count,1)
            final=self.client.get('/api/subscriptions/bilibili:123/videos?offset=30').json()
            self.assertEqual(len(final['items']),2);self.assertFalse(final['has_more']);self.assertEqual(fetch.call_count,2)
    def test_rate_limit_does_not_erase_loaded_videos(self):
        self.subscribed()
        with patch('subscriptions.fetch_bilibili',return_value=self.page(more=True)):
            self.client.get('/api/subscriptions/bilibili:123/videos')
        with patch('subscriptions.fetch_bilibili',side_effect=app.HTTPException(401,'需要登录')):
            self.assertEqual(self.client.get('/api/subscriptions/bilibili:123/videos?offset=30').status_code,401)
            cached=self.client.get('/api/subscriptions/bilibili:123/videos').json()
            self.assertEqual(len(cached['items']),10)

    def test_platform_cooldown_keeps_cached_pages_available(self):
        self.subscribed()
        with patch('subscriptions.fetch_bilibili',return_value=self.page(more=True)):
            self.client.get('/api/subscriptions/bilibili:123/videos')
        with patch('subscriptions.fetch_bilibili',side_effect=app.HTTPException(429,'平台限制')) as fetch:
            for _ in range(2):self.assertEqual(self.client.get('/api/subscriptions/bilibili:123/videos?offset=30').status_code,429)
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(len(self.client.get('/api/subscriptions/bilibili:123/videos').json()['items']),10)
    def prepare_batch(self):
        self.subscribed()
        with patch('subscriptions.fetch_bilibili',return_value=self.page(count=2)):
            self.client.get('/api/subscriptions/bilibili:123/videos')
        return {'video_ids':['BVtest000000','BVtest000001'],'model':'sensevoice','llm_model':'local'}
    def test_batch_is_idempotent_and_queue_has_creator_metadata(self):
        body=self.prepare_batch()
        with patch('app.health',return_value={'models':['local']}),patch.object(app.pool,'submit') as submit:
            first=self.client.post('/api/subscriptions/bilibili:123/import',json=body).json()
            second=self.client.post('/api/subscriptions/bilibili:123/import',json=body).json()
            self.assertEqual(len(first['added']),2);self.assertEqual(len(second['added']),0);self.assertEqual(len(second['skipped']),2)
            self.assertEqual(submit.call_count,2)
            r=app.read(first['added'][0]['job_id']);self.assertEqual(r['creator']['id'],'123');self.assertEqual(r['summary_status'],'pending')
    def test_batch_rejects_unknown_ids_and_missing_model(self):
        body=self.prepare_batch();body['video_ids']=['not-in-list']
        with patch('app.health',return_value={'models':['local']}),patch.object(app.pool,'submit') as submit:
            self.assertEqual(self.client.post('/api/subscriptions/bilibili:123/import',json=body).status_code,400);submit.assert_not_called()
        body['llm_model']=''
        self.assertEqual(self.client.post('/api/subscriptions/bilibili:123/import',json=body).status_code,400)
    def test_batch_pipeline_generates_summary_after_transcription(self):
        body=self.prepare_batch()
        with patch('app.health',return_value={'models':['local']}),patch.object(app.pool,'submit') as submit:
            self.client.post('/api/subscriptions/bilibili:123/import',json=body)
            worker,*args=submit.call_args_list[0].args
        def transcribe(jid,*unused):
            r=app.read(jid);r.update(status='done',text='转写正文');app.save(r)
        def summarize(jid,req):
            self.assertTrue(req.summary);self.assertEqual(req.model,'local')
            r=app.read(jid);r['summary']='生成的核心要点';app.save(r)
        with patch('app.process',side_effect=transcribe),patch('app.chat',side_effect=summarize):worker(*args)
        r=app.read(args[0]);self.assertEqual(r['summary'],'生成的核心要点');self.assertEqual(r['summary_status'],'done')
    def test_summary_failure_preserves_transcript(self):
        body=self.prepare_batch()
        with patch('app.health',return_value={'models':['local']}),patch.object(app.pool,'submit') as submit:
            self.client.post('/api/subscriptions/bilibili:123/import',json=body);worker,*args=submit.call_args_list[0].args
        def transcribe(jid,*unused):
            r=app.read(jid);r.update(status='done',text='转写正文');app.save(r)
        with patch('app.process',side_effect=transcribe),patch('app.chat',side_effect=RuntimeError('model down')):worker(*args)
        r=app.read(args[0]);self.assertEqual(r['text'],'转写正文');self.assertEqual(r['status'],'done');self.assertEqual(r['summary_status'],'error')
    def test_xiaohongshu_video_only_and_token_preserved(self):
        creator={'key':'xiaohongshu:'+'a'*24}
        notes=[{'id':'b'*24,'xsecToken':'token+with=chars','noteCard':{'type':'video','displayTitle':'标题','cover':{'urlDefault':'https://example.test/cover.jpg'}}},{'id':'c'*24,'noteCard':{'type':'normal'}}]
        result=subscriptions.normalize_xhs(notes,creator)
        self.assertEqual(len(result),1);self.assertIn('token%2Bwith%3Dchars',result[0]['url']);self.assertEqual(result[0]['title'],'标题')
    def test_same_video_with_different_share_tokens_is_deduplicated(self):
        self.assertEqual(subscriptions.canonical('https://www.xiaohongshu.com/explore/'+'a'*24+'?xsec_token=one'),subscriptions.canonical('https://www.xiaohongshu.com/discovery/item/'+'a'*24+'?xsec_token=two'))

    def test_short_share_url_uses_resolved_video_identity(self):
        body=self.prepare_batch()
        previous=app.new('分享链接视频','https://b23.tv/short')
        previous.update(status='done',source_identity='bilibili:BVtest000000');app.save(previous)
        with patch('app.health',return_value={'models':['local']}),patch.object(app.pool,'submit'):
            result=self.client.post('/api/subscriptions/bilibili:123/import',json=body).json()
        self.assertEqual(len(result['added']),1);self.assertEqual(len(result['skipped']),1)

    def test_xiaohongshu_skeleton_cards_require_login(self):
        from types import SimpleNamespace
        state={'user':{'notes':[[{'id':'','noteCard':{'type':'video','noteId':''}}]],'noteQueries':[{'cursor':'cursor','hasMore':True}]}}
        response=SimpleNamespace(status_code=200,text='<script>window.__INITIAL_STATE__='+json.dumps(state)+'</script>')
        with patch('curl_cffi.requests.Session') as session:
            session.return_value.__enter__.return_value.get.return_value=response
            with self.assertRaises(app.HTTPException) as error:
                subscriptions.fetch_xiaohongshu({'url':'https://www.xiaohongshu.com/user/profile/'+'a'*24,'key':'xiaohongshu:'+'a'*24},'','')
        self.assertEqual(error.exception.status_code,401)

    def test_xiaohongshu_default_banned_info_is_not_a_ban(self):
        from types import SimpleNamespace
        for banned,code in [(False,401),(True,502)]:
            state={'user':{'notes':[], 'bannedInfo':{'serverBanned':banned,'code':0,'showAlert':False}}}
            response=SimpleNamespace(status_code=200,text='<script>window.__INITIAL_STATE__='+json.dumps(state)+'</script>')
            with patch('curl_cffi.requests.Session') as session:
                session.return_value.__enter__.return_value.get.return_value=response
                with self.assertRaises(app.HTTPException) as error:
                    subscriptions.fetch_xiaohongshu({'url':'https://www.xiaohongshu.com/user/profile/'+'a'*24},'','')
            self.assertEqual(error.exception.status_code,code)
            if not banned:self.assertNotIn('受限状态',error.exception.detail)

    def test_authenticated_xhs_first_page_uses_profile(self):
        from types import SimpleNamespace
        state={'user':{'notes':[[{'id':'b'*24,'noteCard':{'type':'video','noteId':'b'*24,'displayTitle':'Video'}}]],'noteQueries':[{'cursor':'next','hasMore':True}]}}
        response=SimpleNamespace(status_code=200,text='<script>window.__INITIAL_STATE__='+json.dumps(state)+'</script>')
        with patch.object(subscriptions,'browser_cookies',return_value={'a1':'test','web_session':'test'}), patch('curl_cffi.requests.Session') as session:
            session.return_value.__enter__.return_value.get.return_value=response
            page=subscriptions.fetch_xiaohongshu({'url':'https://www.xiaohongshu.com/user/profile/'+'a'*24,'key':'xiaohongshu:'+'a'*24},'','chrome')
        self.assertEqual(len(page['items']),1)
        self.assertEqual(page['cursor'],'next')

    def test_xhs_406_is_not_reported_as_login_failure(self):
        from types import SimpleNamespace
        response=SimpleNamespace(status_code=406,json=lambda:{'code':-1,'success':False})
        with patch.object(subscriptions,'browser_cookies',return_value={'a1':'test'}), patch('xhshow.Xhshow') as signer, patch('curl_cffi.requests.get',return_value=response):
            signer.return_value.sign_headers_get.return_value={}
            with self.assertRaises(app.HTTPException) as error:
                subscriptions.fetch_xiaohongshu({'id':'a'*24,'url':'https://www.xiaohongshu.com'},'next','chrome')
            self.assertEqual(signer.return_value.sign_headers_get.call_args.kwargs['sign_format'],'xyw')
        self.assertIn('406',error.exception.detail)
        self.assertNotIn('确认登录',error.exception.detail)

if __name__=='__main__':
    import unittest
    unittest.main()
