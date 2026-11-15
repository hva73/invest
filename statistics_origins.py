"""Read explicit proposal-to-order evidence; never infer intent from proximity."""
import json
import re
import sqlite3


def signal_order_sides(connect, user_id, portfolio_id):
    """Return explicit, unambiguous provider order references to HOT WATCH proposals.

    A proposal is not a fill. The consumer must independently verify an executed
    order in the same portfolio and direction. Missing or contradictory evidence
    leaves the source unknown.
    """
    try:
        with connect() as db:
            proposals = db.execute("SELECT p.signal_event_id,p.intent_id,p.payload,p.response,e.event_type,s.request FROM broker_proposals p JOIN hw_events e ON e.event_id=p.signal_event_id JOIN hw_sessions s ON s.id=e.watch_row_id "
                                   "WHERE p.user_id=? AND p.portfolio_id=? AND p.kind='direct' AND p.status='sent' AND p.report_id='@hotwatch' AND s.user_id=p.user_id AND s.watch_id=p.candidate_id AND s.is_test=0",
                                   (user_id, portfolio_id)).fetchall()
    except sqlite3.OperationalError:
        return {}
    seen = {}
    for event_id, intent_id, payload, response, event_type, request in proposals:
        if not isinstance(event_id,str) or not re.fullmatch(r'hw-[a-f0-9]{24}',event_id): continue
        try:
            args, result, watch = json.loads(payload), json.loads(response), json.loads(request)
        except (TypeError, ValueError): continue
        if not isinstance(args,dict) or not isinstance(result,dict) or not isinstance(watch,dict): continue
        orders = args.get('orders')
        if not isinstance(orders,list) or len(orders)!=1 or not isinstance(orders[0],dict): continue
        side=orders[0].get('side'); order_id=result.get('orderId'); asset_id=orders[0].get('assetId')
        if side not in ('BUY','SELL') or not isinstance(intent_id,str) or not intent_id: continue
        if not isinstance(asset_id,str) or not asset_id or watch.get('asset_id') != asset_id: continue
        if watch.get('portfolio_ids') != [portfolio_id]: continue
        if event_type not in ({'BUY_SIGNAL'} if side=='BUY' else {'SELL_SIGNAL','REDUCE_SIGNAL'}): continue
        if result.get('orderIntentId')!=intent_id or str(result.get('status','')).upper()!='ACCEPTED': continue
        if not isinstance(order_id,str) or not order_id or len(order_id)>200: continue
        if order_id in seen:
            seen[order_id]=None
        else:
            seen[order_id]=(side,asset_id)
    return {key: value for key,value in seen.items() if value is not None}
