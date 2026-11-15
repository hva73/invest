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
            proposals = db.execute("SELECT signal_event_id,intent_id,payload,response FROM broker_proposals "
                                   "WHERE user_id=? AND portfolio_id=? AND kind='direct' AND status='sent'",
                                   (user_id, portfolio_id)).fetchall()
    except sqlite3.OperationalError:
        return {}
    seen = {}
    for event_id, intent_id, payload, response in proposals:
        if not isinstance(event_id,str) or not re.fullmatch(r'hw-[a-f0-9]{24}',event_id): continue
        try:
            args, result = json.loads(payload), json.loads(response)
        except (TypeError, ValueError): continue
        if not isinstance(args,dict) or not isinstance(result,dict): continue
        orders = args.get('orders')
        if not isinstance(orders,list) or len(orders)!=1 or not isinstance(orders[0],dict): continue
        side=orders[0].get('side'); order_id=result.get('orderId')
        if side not in ('BUY','SELL') or not isinstance(intent_id,str) or not intent_id: continue
        if result.get('orderIntentId')!=intent_id or str(result.get('status','')).upper()!='ACCEPTED': continue
        if not isinstance(order_id,str) or not order_id or len(order_id)>200: continue
        if order_id in seen:
            seen[order_id]=None
        else:
            seen[order_id]=(side,event_id)
    return {key: value[0] for key,value in seen.items() if value is not None}
