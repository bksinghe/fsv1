"""Actor detail hides attached videos without deleting them; Posts keep them."""
import ast
import html
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
CAT=(ROOT/'web/catalog.py').read_text()
ROUTES=(ROOT/'web/catalog_routes.py').read_text()


class ActorAttachedUITests(unittest.TestCase):
    def test_actor_hides_attachment_section_button_and_count_but_post_keeps_them(self):
        tree=ast.parse(CAT)
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_detail_body')
        base={'categories':[],'galleryTab':'Gallery','videosHeading':'Attached Videos',
              'videoEmptyHint':'None','galleryEmpty':'None','uploadLabel':'Upload','galleryHint':'Hint',
              'base':'/catalog'}
        actor=dict(base,tagMedia=True);post=dict(base,tagMedia=False)
        env={'html':html,'quote':quote,'CATALOGS':{'posts':post,'actors':actor},
             'image_src':lambda v:v or '', 'video_card_html':lambda fid,label,poster,data: '<article>'+label+'</article>',
             'SEARCH_FILTERS':({'id':'mode'},{'id':'group'}),'filter_buttons':lambda specs:'<div>filters</div>'}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<catalog>','exec'),env)
        item={'id':'abc','title':'Test','tags':['Actor'], 'videos':[{'file_id':'id','label':'SECRET ATTACHMENT'}]}
        for role in ('user','admin'):
            with self.subTest(role=role):
                body=env['_detail_body']('actors',role,item)
                self.assertNotIn('Attached Videos',body);self.assertNotIn('SECRET ATTACHMENT',body)
                self.assertNotIn('id="catVideos"',body);self.assertNotIn('Add Videos</a>',body)
                self.assertIn('id="catMediaResults"',body);self.assertIn('filters',body)
                self.assertNotIn('class="cat-tab-n">1</span></button>',body)
        post_body=env['_detail_body']('posts','admin',item)
        self.assertIn('SECRET ATTACHMENT',post_body);self.assertIn('id="catVideos"',post_body)
        self.assertIn('🎬 Add Videos</a>',post_body);self.assertIn('class="cat-tab-n">1</span>',post_body)
        self.assertEqual(item['videos'][0]['file_id'],'id')


class ActorDetailRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_post_detail_enriches_attached_videos(self):
        tree=ast.parse(ROUTES)
        fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_detail')
        enrich=AsyncMock()
        env={'get_auth':AsyncMock(return_value=('admin',1)), 'web':SimpleNamespace(HTTPFound=lambda x:x,Response=lambda **kw:kw),
             'store':SimpleNamespace(get_item=AsyncMock(return_value={'videos':[{'file_id':'1'}]})),
             '_visible_attachments':AsyncMock(side_effect=lambda items:items), '_safe_item':lambda kind,item:item,'_clean_id':lambda x:x,'_enrich_attached_videos':enrich,
             'build_detail_page':lambda kind,role,uid,item:kind}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<routes>','exec'),env)
        self.assertEqual(await env['_detail'](None,'actors','x'),'actors');enrich.assert_not_awaited()
        self.assertEqual(await env['_detail'](None,'posts','x'),'posts');enrich.assert_awaited_once()
