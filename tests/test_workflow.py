"""Offline behavioral checks; no network, model downloads, or real user files."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import library as lib
import runtime as rt


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = dict(bvid='BV17N411B7Ya', cid=123, page=1, title='测试来源', author='作者',
                           duration=20, url='https://www.bilibili.com/video/BV17N411B7Ya/?p=1')
        self.item = dict(id='BV17N411B7Ya-p1', source=self.source)
        self.folder = self.root/'library'/self.item['id']
        self.raw = dict(complete=True, duration=20, signature=dict(cid=123, kind='caption'),
                       segments=[dict(id='s001',start=1,end=18,text='示例原文')])
        rt.write(self.folder/'source.json', self.source)
        rt.write(self.folder/'raw.json', self.raw)
        self.article = dict(title='测试笔记', tags=['测试'], takeaways=['要点'], caveats=['机器稿'],
            transcript_sha256=rt.digest(self.folder/'raw.json'), knowledge=[dict(title='知识点', explanation='说明', source_ids=['s001'])])
        rt.write(self.folder/'article.json', self.article)

    def tearDown(self):
        self.temp.cleanup()

    def test_identity_and_multipart(self):
        self.assertEqual(lib.identity(self.source['url']+'&spm_id_from=abc'), ('video','BV17N411B7Ya',1))
        self.assertEqual(lib.identity('https://www.bilibili.com/video/BV17N411B7Ya/')[2], None)
        for value in ('file:///etc/passwd','https://evil.example/video/BV17N411B7Ya','https://www.bilibili.com/video/BV17N411B7Ya/?p=0'):
            with self.assertRaises(ValueError): lib.identity(value)

    def test_entry_path_escape_rejected(self):
        with self.assertRaises(ValueError): lib.entry_path(self.root, '../../elsewhere')

    def test_cached_transcript_needs_no_install(self):
        with patch.object(lib,'prepare_asr',side_effect=AssertionError('should not install')):
            folder = lib.prepare(self.item,self.root,self.root/'runtime',Path('uv'),None)
        self.assertEqual(folder,self.folder)
        self.assertEqual(rt.read(folder/'source-package.json')['quality_status'],'unreviewed_machine_transcript')

    def test_subtitle_skips_model(self):
        (self.folder/'raw.json').unlink()
        with patch.object(lib,'caption_raw',return_value=self.raw), patch.object(lib,'prepare_asr',side_effect=AssertionError('should not install')):
            lib.prepare(self.item,self.root,self.root/'runtime',Path('uv'),None)
        self.assertTrue(rt.read(self.folder/'raw.json')['complete'])

    def test_publish_same_data_and_safe_embedding(self):
        self.article['knowledge'][0]['explanation'] = '</script><img src=x onerror=alert(1)>'
        rt.write(self.folder/'article.json',self.article)
        before=rt.digest(self.folder/'raw.json')
        lib.publish(self.folder,self.root)
        page=(self.root/'index.html').read_text(encoding='utf-8')
        self.assertNotIn('</script><img',page)
        payload=page.split('<script id="data" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload),[rt.read(self.folder/'entry.json')])
        self.assertIn('示例原文',(self.folder/'note.md').read_text(encoding='utf-8'))
        self.assertEqual(before,rt.digest(self.folder/'raw.json'))

    def test_stale_or_incomplete_source_rejected(self):
        self.article['transcript_sha256']='outdated'; rt.write(self.folder/'article.json',self.article)
        with self.assertRaises(ValueError): lib.publish(self.folder,self.root)
        self.raw['complete']=False; rt.write(self.folder/'raw.json',self.raw)
        with self.assertRaises(ValueError): lib.publish(self.folder,self.root)

    def test_invalid_citation_rejected(self):
        self.article['knowledge'][0]['source_ids']=['missing']; rt.write(self.folder/'article.json',self.article)
        with self.assertRaises(ValueError): lib.publish(self.folder,self.root)

    def test_frame_escape_rejected(self):
        (self.root/'outside.jpg').write_bytes(b'not-a-real-image')
        rt.write(self.folder/'frames.json',[dict(id='f1',second=1,file='../../../outside.jpg')])
        with self.assertRaises(ValueError): lib.publish(self.folder,self.root)

    def test_coverage_includes_head_and_tail(self):
        self.raw['segments'][0].update(start=10,end=20); self.raw['duration']=40
        lib.package(self.folder,self.raw)
        gaps=rt.read(self.folder/'source-package.json')['issues']
        self.assertEqual([(g['start'],g['end']) for g in gaps],[(0,10),(20,40)])

    def test_download_corruption_never_promoted(self):
        target=self.root/'model.bin'
        with patch.object(rt.urllib.request,'urlopen',side_effect=lambda *a,**k:io.BytesIO(b'corrupt')), patch.object(rt.time,'sleep'):
            with self.assertRaises(RuntimeError): rt.download('https://example.com/model',target,sha='0'*64)
        self.assertFalse(target.exists())
        self.assertTrue(target.with_name('model.bin.partial').exists())

    def test_collection_pagination_keeps_favorite_entry_boundary(self):
        client=lib.Bili()
        favorite=dict(id=1,bvid='BV17N411B7Ya',type=2,page=81,ugc=dict(first_cid=1))
        pages=[dict(medias=[favorite],has_more=True),
               dict(medias=[favorite,dict(id=2,bvid='BV1ox4y1A7UJ',type=2),dict(id=3,title='失效',type=2)],has_more=False)]
        meta=dict(title='视频',owner=dict(name='作者'),pages=[dict(page=n,cid=n,part=str(n),duration=10) for n in range(1,82)])
        with patch.object(client,'api',side_effect=pages),patch.object(client,'view',return_value=meta):
            state=client.plan('https://space.bilibili.com/123/favlist?fid=456')
        self.assertEqual([i['id'] for i in state['items']],['BV17N411B7Ya-p1','BV1ox4y1A7UJ-p1'])
        self.assertEqual(state['selected_video_count'],2)
        self.assertEqual(len(state['unavailable']),1)

    def test_parts_only_expand_when_explicitly_requested(self):
        client=lib.Bili()
        meta=dict(title='视频',owner=dict(name='作者'),pages=[dict(page=1,cid=1,part='上',duration=10),dict(page=2,cid=2,part='下',duration=10)])
        url='https://www.bilibili.com/video/BV17N411B7Ya/'
        with patch.object(client,'view',return_value=meta):
            self.assertEqual([i['source']['page'] for i in client.plan(url)['items']],[1])
            self.assertEqual([i['source']['page'] for i in client.plan(url,all_parts=True)['items']],[1,2])
            self.assertEqual([i['source']['page'] for i in client.plan(url+'?p=2',all_parts=True)['items']],[2])

    def test_build_excludes_old_out_of_scope_entries(self):
        lib.publish(self.folder,self.root)
        rt.write(self.root/'batch-state.json',dict(items=[]))
        lib.build(self.root)
        self.assertEqual(rt.read(self.root/'search-index.json'),[])
        page=(self.root/'index.html').read_text(encoding='utf-8')
        payload=page.split('<script id="data" type="application/json">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload),[])

    def test_collection_repeated_page_is_not_complete(self):
        client=lib.Bili(); page=dict(medias=[dict(id=1,bvid='BV17N411B7Ya')],has_more=True)
        with patch.object(client,'api',return_value=page):
            with self.assertRaises(RuntimeError): client.plan('https://space.bilibili.com/123/favlist?fid=456')

    def test_media_refreshes_expired_signed_url(self):
        client=lib.Bili(); response=dict(dash=dict(audio=[dict(bandwidth=1,baseUrl='https://example.com/a')]))
        with patch.object(client,'api',return_value=response) as api, patch.object(lib,'download',side_effect=[RuntimeError('expired'),'downloaded']):
            self.assertEqual(client.media(self.source,'audio',self.root/'audio.m4a'),'downloaded')
        self.assertEqual(api.call_count,2)


if __name__=='__main__':
    unittest.main()
