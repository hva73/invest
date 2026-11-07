import io,unittest,zipfile
from ssga_holdings import parse,HoldingsUnavailable

class IssuerHoldingsTest(unittest.TestCase):
 def workbook(self):
  buf=io.BytesIO()
  with zipfile.ZipFile(buf,'w') as z:
   z.writestr('xl/worksheets/sheet1.xml','''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
   <row><c r="A1" t="inlineStr"><is><t>Ticker Symbol:</t></is></c><c r="B1" t="inlineStr"><is><t>XLU</t></is></c></row>
   <row><c r="A7" t="inlineStr"><is><t>Holdings:</t></is></c><c r="B7" t="inlineStr"><is><t>As of 05-Nov-2026</t></is></c></row>
   <row><c r="A2" t="inlineStr"><is><t>Ticker</t></is></c><c r="B2" t="inlineStr"><is><t>Name</t></is></c><c r="C2" t="inlineStr"><is><t>Weight</t></is></c></row>
   <row><c r="A3" t="inlineStr"><is><t>NEE</t></is></c><c r="B3" t="inlineStr"><is><t>NextEra Energy</t></is></c><c r="C3" s="1"><v>0.12</v></c></row>
   <row><c r="A4" t="inlineStr"><is><t>SO</t></is></c><c r="B4" t="inlineStr"><is><t>Southern Company</t></is></c><c r="C4"><v>5.3</v></c></row>
   <row><c r="A5" t="inlineStr"><is><t>NEE</t></is></c><c r="B5" t="inlineStr"><is><t>Duplicate</t></is></c><c r="C5"><v>2</v></c></row>
   <row><c r="A6" t="inlineStr"><is><t>-</t></is></c><c r="B6" t="inlineStr"><is><t>Cash</t></is></c><c r="C6"><v>0.1</v></c></row>
   </sheetData></worksheet>''')
   z.writestr('xl/styles.xml','''<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs><xf numFmtId="0"/><xf numFmtId="10"/></cellXfs></styleSheet>''')
  return buf.getvalue()
 def test_parses_and_sorts_published_weights(self):
  result=parse(self.workbook(),'XLU');rows=result['rows'];self.assertEqual(result['as_of'],'2026-11-05')
  self.assertEqual([r['ticker'] for r in rows],['NEE','SO']);self.assertAlmostEqual(rows[0]['weight'],12);self.assertEqual(rows[1]['weight'],5.3)
 def test_accepts_observed_xlu_column_layout_and_fund_date(self):
  rows=[['Fund Name:','State Street Utilities Select Sector SPDR ETF'],['Ticker Symbol:','XLU'],['Holdings:','As of 05-Nov-2026'],['Name','Ticker','Identifier','SEDOL','Weight','Sector','SharesHeld','Local Currency'],['NEXTERA ENERGY INC','NEE','65339F101','2328915','13.520687','-','36033044','USD'],['SOUTHERN CO/THE','SO','842587107','2829601','7.886402','-','19871380','USD']]
  from xml.sax.saxutils import escape
  xml='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
  for ri,row in enumerate(rows,1):
   xml+='<row>'+''.join('<c r="'+chr(65+ci)+str(ri)+'" t="inlineStr"><is><t>'+escape(value)+'</t></is></c>' for ci,value in enumerate(row))+'</row>'
  xml+='</sheetData></worksheet>'
  buf=io.BytesIO()
  with zipfile.ZipFile(buf,'w') as z:z.writestr('xl/worksheets/sheet1.xml',xml)
  data=parse(buf.getvalue(),'XLU')
  self.assertEqual(data['as_of'],'2026-11-05');self.assertEqual([(x['ticker'],x['weight']) for x in data['rows']],[('NEE',13.520687),('SO',7.886402)])
 def test_rejects_unknown_fund_and_invalid_workbook(self):
  with self.assertRaises(HoldingsUnavailable):parse(self.workbook(),'XLK')
  with self.assertRaises(HoldingsUnavailable):parse(self.workbook(),'BAD')
  with self.assertRaises(HoldingsUnavailable):parse(b'not a workbook','XLU')
