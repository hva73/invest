import sqlite3, unittest
import user_profile

class ProfileTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
  self.db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY)');self.db.executemany('INSERT INTO users VALUES(?)',[(1,),(2,)])
  user_profile.init(self.db)
  self.valid={'name':'Test Person','email':'person@example.org','street':'Testvej 1','postal_code':'7140','city':'Stouby','birth_date':'1980-02-29','contact_consent':False,'marketing_consent':False}
 def test_start_persists_and_profiles_are_isolated(self):
  self.assertFalse(user_profile.read(self.db,1)['started'])
  self.assertFalse(user_profile.start(self.db,1)['complete'])
  self.assertFalse(user_profile.read(self.db,2)['started'])
  result=user_profile.save(self.db,1,self.valid,'2026-11-08')
  self.assertTrue(result['complete']);self.assertFalse(result['marketing_consent']);self.assertFalse(result['contact_consent'])
  self.assertFalse(user_profile.read(self.db,2)['started'])
 def test_existing_database_is_migrated_without_losing_address(self):
  self.db.execute('DROP TABLE user_profiles')
  self.db.execute("CREATE TABLE user_profiles(user_id INTEGER PRIMARY KEY, started INTEGER NOT NULL DEFAULT 1, name TEXT, email TEXT, address TEXT, birth_date TEXT, contact_consent INTEGER, marketing_consent INTEGER, updated TEXT)")
  self.db.execute("INSERT INTO user_profiles(user_id,address) VALUES(1,?)",('Testvej 1, 7140 Stouby',))
  user_profile.init(self.db)
  profile=user_profile.read(self.db,1)
  self.assertEqual(profile['address'],'Testvej 1, 7140 Stouby')
  self.assertEqual(profile['city'],'Stouby')
 def test_legacy_address_is_preserved_and_split_for_review(self):
  self.db.execute("INSERT INTO user_profiles(user_id,address) VALUES(1,?)",('Testvej 1, 7140 Stouby',))
  p=user_profile.read(self.db,1);self.assertEqual((p['street'],p['postal_code'],p['city']),('Testvej 1','7140','Stouby'))
  self.assertEqual(p['address'],'Testvej 1, 7140 Stouby')
 def test_invalid_and_missing_fields_do_not_save(self):
  for key,value in [('name',' '),('email','bad'),('street',''),('postal_code','12'),('city',''),('birth_date','2099-01-01'),('birth_date','2025-02-29'),('marketing_consent',None),('contact_consent','no')]:
   data={**self.valid,key:value}
   with self.assertRaises(ValueError):user_profile.save(self.db,1,data,'now')
  self.assertFalse(user_profile.read(self.db,1)['started'])

if __name__=='__main__': unittest.main()
