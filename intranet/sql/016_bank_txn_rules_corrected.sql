-- 'bluevine' => marketing was the worst of the seeded guesses: Bluevine is the
-- BANK, not a vendor. It appears in loan payments ("TD BANK, PAYMENT ,
-- BLUEVINE CHECKI") and inter-entity ACH descriptors, so the rule was about to
-- book debt service and transfers as marketing spend.
delete from bank_txn_rules where pattern = 'bluevine';

insert into bank_txn_rules (pattern, category, counterparty, direction, is_internal, note) values
-- Own-entity wires: the OUTBOUND leg says "transfer" and the INBOUND leg says
-- "FEDWIRE CREDIT", so the generic 'transfer' rule caught one side only and
-- the other was landing in income. $90k out, $90k in, same two days.
('wire transfer outgoing first generation','transfer','First Generation USA LLC','out',true,'TD->Chase own-entity wire; pairs with FEDWIRE CREDIT inbound'),
('fedwire credit via: td bank','transfer','First Generation USA LLC','in',true,'inbound leg of the same own-entity wire'),
-- Inter-entity movement between LLCs we own. Real for a single entity P&L,
-- double-counting in a consolidated view, so flagged internal.
('bath tune-up blo, cr offset','transfer','Bath Tune-Up Bloomfield',null,true,'inter-entity offset, NOT customer revenue'),
('first generation, ach pmt','transfer','First Generation USA LLC','in',true,'inter-entity'),
('to bathtuneup','transfer','Bath Tune-Up','out',true,'inter-entity'),
('bathtune up llc','transfer','Bath Tune-Up','out',true,'inter-entity'),
('earthwise','transfer','Earthwise','out',true,'inter-entity'),
('jatalia marketpl','transfer','Jatalia Marketplace','in',true,'inter-entity'),
('oracabessa llc','transfer','Oracabessa LLC','in',true,'inter-entity'),
-- Customer money arriving. Named because these are the descriptors that
-- actually carry revenue, and none of them were in the seed.
('kitchen tune-up','revenue','Kitchen Tune-Up merchant','in',false,'merchant/deposit descriptor for KTU customer receipts'),
('bankcard dep','revenue','BankCard (processor)',null,false,'card settlement net of fees'),
('merch dep','revenue','BankCard (processor)',null,false,'card settlement'),
('remote online deposit','revenue','customer deposit',null,false,'cheque deposit'),
('mobile deposit','revenue','customer deposit',null,false,'cheque deposit'),
('returned mobile deposit','fees','bounced deposit','out',false,'deposit reversed - NOT revenue, cancels the matching deposit'),
('vacp treas','revenue','VA (government payer)','in',false,'VA benefit paying for a job; government payer, still customer revenue'),
('amazon.c','revenue','Amazon','in',false,'Jatalia/Earthwise marketplace settlement'),
-- Labour. Fixed 1099 crew on a bi-weekly cadence.
('miguel bara','labour','Miguel Bara','out',false,'fixed 1099 crew'),
('oscar patri','labour','Oscar Yupa Herrera','out',false,'fixed 1099 crew'),
('jerson godoy','labour','Jerson Godoy','out',false,'fixed 1099 crew'),
('amanda borc','labour','Amanda Borc','out',false,'subcontractor'),
('zelle payment to rocco','labour','Rocco','out',false,'recurring $3,440 bi-weekly - same cadence as the 1099 crew, confirm who this is'),
('benpayrollaccount','labour','Ben','out',false,'payroll'),
-- Materials and trades
('orozco','materials','Orozco Bros','out',false,'countertops'),
('rossi plumbing','subcontractor','Rossi Plumbing','out',false,''),
('home depot','materials','The Home Depot','out',false,''),
('ezdia','materials','EZDIA INC','out',false,''),
-- Financing and occupancy
('promissory note','financing','Promissory Note',null,false,'loan proceeds/payments'),
('td bank, payment','financing','TD Bank','out',false,'loan/LOC payment - NOT marketing'),
('transfer from cl x9001','financing','credit line','in',false,'credit line draw'),
('transfer to cl x9001','financing','credit line','out',false,'credit line repayment'),
('regina re holdin','rent','Regina RE Holdings','out',false,''),
('1285 mp realty','rent','1285 MP Realty','out',false,''),
-- Card payments between our own accounts
('payment received -- thank you','transfer','card payment',null,true,'card payment received - internal'),
('transfer to cc x7905','transfer','TD credit card','out',true,'card payment - internal'),
('flexcreditcard','transfer','Flex card','out',true,'card payment - internal'),
('brex card','transfer','Brex card','out',true,'card payment - internal'),
-- Owner
('zelle payment to takia','owner','Takia Livingston','out',false,'owner draw'),
('to steven livi','owner','Steven Livingston','out',false,'owner draw'),
('steven livin','owner','Steven Livingston','out',false,'owner draw')
on conflict do nothing;

-- Truthifi types several genuine vendor payments as 'transfer'. The same Elias
-- payment appears as 'out' one week and 'transfer' the next, and
-- payables_reconciled only joins on direction='out' — so real bills could
-- never match. Correcting the direction where the description names an
-- outbound payment to an external party.
update bank_transactions set direction='out'
where direction='transfer'
  and (description ilike '%ACH Payment%to Elias%' or description ilike '%to HFC %'
    or description ilike '%to Miguel Bara%' or description ilike '%to Oscar Patri%'
    or description ilike '%to Jerson Godoy%' or description ilike '%to Amanda Borc%'
    or description ilike 'Zelle payment to Rocco%');
