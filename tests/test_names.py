import unittest
from lumesync.names import component, allocate


class NamesTests(unittest.TestCase):
    def test_linux_unsafe_names_stay_single_components(self):
        for original in ['a/b',r'a\b','.', '..', '', '\x00', 'line\nbreak', 'a'*500,'ação'*100]:
            with self.subTest(name=repr(original)):
                value=component(original)
                self.assertNotIn('/',value);self.assertNotIn('\\',value)
                self.assertNotIn(value,('', '.', '..'))
                self.assertLessEqual(len(value.encode()),255)

    def test_escaped_literal_does_not_collide(self):
        cache={};resources=[{'id':'a','name':'a/b'},{'id':'b','name':'a%2Fb'}]
        result=allocate(resources,'parent',cache)
        self.assertEqual(len(set(result.values())),2)

    def test_duplicate_mapping_survives_sibling_removal_and_reordering(self):
        cache={};resources=[{'id':'b','name':'same'},{'id':'a','name':'same'}]
        result=allocate(resources,'parent',cache)
        self.assertEqual(result,allocate(list(reversed(resources)),'parent',cache))
        self.assertEqual(result['b'],allocate([resources[0]],'parent',cache)['b'])

    def test_natural_name_cannot_steal_existing_alias(self):
        cache={};resources=[{'id':'a','name':'same'},{'id':'b','name':'same'}]
        first=allocate(resources,'parent',cache)
        later=resources+[{'id':'c','name':first['b']}]
        result=allocate(later,'parent',cache)
        self.assertEqual(result['b'],first['b']);self.assertEqual(len(set(result.values())),3)

    def test_rename_updates_alias(self):
        cache={};allocate([{'id':'a','name':'old'}],'p',cache)
        result=allocate([{'id':'a','name':'new'}],'p',cache)
        self.assertEqual(result['a'],'new')

    def test_new_local_literal_alias_can_be_preserved(self):
        cache={'id':{'parent':'p','name':'a%2Fb','local':'a%2Fb'}}
        self.assertEqual(allocate([{'id':'id','name':'a%2Fb'}],'p',cache)['id'],'a%2Fb')


if __name__=='__main__':unittest.main()
