import sqlite3, unittest
import user_profile

class ProfileTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
  self.db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)');self.db.executemany('INSERT INTO users VALUES(?)',[(1,),(2,)])
  user_profile.init(self.db)
  self.valid={'name':'Test Person','email':'person@example.org','address':'Testvej 1','birth_date':'1980-02-29','contact_consent':False,'marketing_consent':False}
 def test_start_persists_and_profiles_are_isolated(self):
  self.assertFalse(user_profile.read(self.db,1)['started'])
  self.assertFalse(user_profile.start(self.db,1)['complete'])
  self.assertFalse(user_profile.read(self.db,2)['started'])
  result=user_profile.save(self.db,1,self.valid,'2026-11-08')
  self.assertTrue(result['complete']);self.assertFalse(result['marketing_consent']);self.assertFalse(result['contact_consent'])
  self.assertFalse(user_profile.read(self.db,2)['started'])
 def test_invalid_and_missing_fields_do_not_save(self):
  for key,value in [('name',' '),('email','bad'),('address',''),('birth_date','2099-01-01'),('birth_date','2025-02-29'),('marketing_consent',None),('contact_consent','no')]:
   data={**self.valid,key:value}
   with self.assertRaises(ValueError):user_profile.save(self.db,1,data,'now')
  self.assertFalse(user_profile.read(self.db,1)['started'])

if __name__=='__main__': unittest.main()
