from tvm_valuetypes.cell import deserialize_boc, Cell
from tvm_valuetypes.dict_utils import parse_hashmap
import codecs
from copy import copy
from bitarray import bitarray
from bitarray.util import ba2int, ba2hex, hex2ba
import math
import json
from hashlib import sha256

class Slice:
    def __init__(self, cell: Cell):
        self._data = cell.data.data
        self._data_offset = 0
        self._refs = cell.refs
        self._refs_offset = 0
        
    def prefetch_next(self, bits_count: int):
        return self._data[self._data_offset : self._data_offset + bits_count]

    def read_next(self, bits_count: int):
        result = self._data[self._data_offset : self._data_offset + bits_count]
        self._data_offset += bits_count
        return result

    def read_next_ref(self):
        cell = self._refs[self._refs_offset]
        self._refs_offset += 1
        return Slice(cell)
    
    def read_uint(self, bits_count: int):
        return ba2int(self.read_next(bits_count), signed=False)
        
    def read_var_uint(self, max_len: int):
        """
        var_uint$_ {n:#} len:(#< n) value:(uint (len * 8))
                 = VarUInteger n;
        """
        header_bits = math.ceil(math.log2(max_len))
        uint_len = ba2int(self.read_next(header_bits), signed=False)
        if uint_len == 0:
            return 0
        return ba2int(self.read_next(uint_len * 8), signed=False)
    
    def bits_left(self):
        return len(self._data) - self._data_offset

    def refs_left(self):
        return len(self._refs) - self._refs_offset

    def raise_if_not_empty(self):
        assert self.bits_left() == 0, f"Parsing error - slice has {self.bits_left()} unread bits left."
        assert self.refs_left() == 0, f"Parsing error - slice has {self.refs_left()} unread refs left."

    
class CurrencyCollection:
    """
    nanograms$_ amount:(VarUInteger 16) = Grams;
    extra_currencies$_ dict:(HashmapE 32 (VarUInteger 32)) 
                     = ExtraCurrencyCollection;
    currencies$_ grams:Grams other:ExtraCurrencyCollection 
               = CurrencyCollection;
    """
    def __init__(self, slice: Slice):
        self.grams = slice.read_var_uint(16)
        extra_currency_collection_empty = slice.read_next(1)
        if extra_currency_collection_empty == bitarray('1'):
            extra_currency_collection = slice.read_next_ref() # TODO: parse hashmap 

            
class TrStoragePhase:
    """
    tr_phase_storage$_ storage_fees_collected:Grams 
      storage_fees_due:(Maybe Grams)
      status_change:AccStatusChange
      = TrStoragePhase;
    """
    def __init__(self, cell_slice: Slice):
        self.storage_fees_collected = cell_slice.read_var_uint(16)
        self.storage_fees_due = cell_slice.read_var_uint(16) if cell_slice.read_next(1).any() else None
        account_status_change = cell_slice.read_next(1)
        if account_status_change == bitarray('0'):
            self.status_change = 'acst_unchanged'
        else:
            account_status_change += cell_slice.read_next(1)
            if account_status_change == bitarray('10'):
                self.status_change = 'acst_frozen'
            else:
                self.status_change = 'acst_deleted'
        
class TrCreditPhase:
    """
    tr_phase_credit$_ due_fees_collected:(Maybe Grams)
      credit:CurrencyCollection = TrCreditPhase;
    """
    def __init__(self, cell_slice: Slice):
        self.due_fees_collected = cell_slice.read_var_uint(16) if cell_slice.read_next(1).any() else None
        self.credit = CurrencyCollection(cell_slice)

class TrComputePhase:
    """
    tr_phase_compute_skipped$0 reason:ComputeSkipReason
      = TrComputePhase;
    tr_phase_compute_vm$1 success:Bool msg_state_used:Bool 
      account_activated:Bool gas_fees:Grams
      ^[ gas_used:(VarUInteger 7)
      gas_limit:(VarUInteger 7) gas_credit:(Maybe (VarUInteger 3))
      mode:int8 exit_code:int32 exit_arg:(Maybe int32)
      vm_steps:uint32
      vm_init_state_hash:bits256 vm_final_state_hash:bits256 ]
      = TrComputePhase;
    cskip_no_state$00 = ComputeSkipReason;
    cskip_bad_state$01 = ComputeSkipReason;
    cskip_no_gas$10 = ComputeSkipReason;
    """
    def __init__(self, cell_slice: Slice):
        if cell_slice.read_next(1).any():
            self.type = 'tr_phase_compute_vm'
            self.success = cell_slice.read_next(1).any()
            self.msg_state_used = cell_slice.read_next(1).any()
            self.account_activated = cell_slice.read_next(1).any()
            self.gas_fees = cell_slice.read_var_uint(16)
            
            subcell_slice = cell_slice.read_next_ref()
            self.gas_used = subcell_slice.read_var_uint(7)
            self.gas_limit = subcell_slice.read_var_uint(7)
            self.gas_credit = subcell_slice.read_var_uint(3) if subcell_slice.read_next(1).any() else None
            self.mode = ba2int(subcell_slice.read_next(8), signed=True)
            self.exit_code = ba2int(subcell_slice.read_next(32), signed=True)
            self.exit_arg = ba2int(subcell_slice.read_next(32), signed=True) if subcell_slice.read_next(1).any() else None
            self.vm_steps = ba2int(subcell_slice.read_next(32), signed=False)
            self.vm_init_state_hash = ba2hex(subcell_slice.read_next(256))
            self.vm_final_state_hash = ba2hex(subcell_slice.read_next(256))
            assert subcell_slice.bits_left() == 0
        else:
            self.type = 'tr_phase_compute_skipped'
            reason = cell_slice.read_next(2)
            if reason == bitarray('00'):
                self.reason = 'cskip_no_state'
            elif reason == bitarray('01'):
                self.reason = 'cskip_bad_state'
            elif reason == bitarray('10'):
                self.reason = 'cskip_no_gas'

class StorageUsedShort:
    """
    storage_used_short$_ cells:(VarUInteger 7) 
      bits:(VarUInteger 7) = StorageUsedShort;
    """
    def __init__(self, cell_slice: Slice):
        self.cells = cell_slice.read_var_uint(7)
        self.bits = cell_slice.read_var_uint(7)
        
class TrActionPhase:
    """
    tr_phase_action$_ success:Bool valid:Bool no_funds:Bool
      status_change:AccStatusChange
      total_fwd_fees:(Maybe Grams) total_action_fees:(Maybe Grams)
      result_code:int32 result_arg:(Maybe int32) tot_actions:uint16
      spec_actions:uint16 skipped_actions:uint16 msgs_created:uint16 
      action_list_hash:bits256 tot_msg_size:StorageUsedShort 
      = TrActionPhase;
    """
    def __init__(self, cell_slice: Slice):
        self.success = cell_slice.read_next(1).any()
        self.valid = cell_slice.read_next(1).any()
        self.no_funds = cell_slice.read_next(1).any()
        account_status_change = cell_slice.read_next(1)
        if account_status_change == bitarray('0'):
            self.status_change = 'acst_unchanged'
        else:
            account_status_change += cell_slice.read_next(1)
            if account_status_change == bitarray('10'):
                self.status_change = 'acst_frozen'
            else:
                self.status_change = 'acst_deleted'
        self.total_fwd_fees = cell_slice.read_var_uint(16) if cell_slice.read_next(1).any() else None
        self.total_action_fees = cell_slice.read_var_uint(16) if cell_slice.read_next(1).any() else None
        self.result_code = ba2int(cell_slice.read_next(32), signed=True)
        self.result_arg = ba2int(cell_slice.read_next(32), signed=True) if cell_slice.read_next(1).any() else None
        self.tot_actions = ba2int(cell_slice.read_next(16), signed=False)
        self.spec_actions = ba2int(cell_slice.read_next(16), signed=False)
        self.skipped_actions = ba2int(cell_slice.read_next(16), signed=False)
        self.msgs_created = ba2int(cell_slice.read_next(16), signed=False)
        self.action_list_hash = ba2hex(cell_slice.read_next(256))
        self.tot_msg_size = StorageUsedShort(cell_slice)
        
class TrBouncePhase:
    """
    tr_phase_bounce_negfunds$00 = TrBouncePhase;
    tr_phase_bounce_nofunds$01 msg_size:StorageUsedShort
      req_fwd_fees:Grams = TrBouncePhase;
    tr_phase_bounce_ok$1 msg_size:StorageUsedShort 
      msg_fees:Grams fwd_fees:Grams = TrBouncePhase;
    """
    def __init__(self, cell_slice: Slice):
        prefix = cell_slice.read_next(1)
        if prefix == bitarray('1'):
            self.type = 'tr_phase_bounce_ok'
            self.msg_size = StorageUsedShort(cell_slice)
            self.msg_fees = cell_slice.read_var_uint(16)
            self.fwd_fees = cell_slice.read_var_uint(16)
        else:
            prefix += cell_slice.read_next(1)
            if prefix == bitarray('00'):
                self.type = 'tr_phase_bounce_negfunds'
            else:
                self.type = 'tr_phase_bounce_nofunds'
                self.msg_size = StorageUsedShort(cell_slice)
                self.req_fwd_fees = cell_slice.read_var_uint(16)
                
class SplitMergeInfo:
    """
    split_merge_info$_ cur_shard_pfx_len:(## 6)
      acc_split_depth:(## 6) this_addr:bits256 sibling_addr:bits256
      = SplitMergeInfo;
    """
    def __init__(self, cell_slice: Slice):
        self.cur_shard_pfx_len = ba2int(cell_slice.read_next(6), signed=False)
        self.acc_split_depth = ba2int(cell_slice.read_next(6), signed=False)
        self.this_addr = ba2hex(cell_slice.read_next(256))
        self.sibling_addr = ba2hex(cell_slice.read_next(256))
            
class TransactionDescr:
    """
    trans_ord$0000 credit_first:Bool
      storage_ph:(Maybe TrStoragePhase)
      credit_ph:(Maybe TrCreditPhase)
      compute_ph:TrComputePhase action:(Maybe ^TrActionPhase)
      aborted:Bool bounce:(Maybe TrBouncePhase)
      destroyed:Bool
      = TransactionDescr;

    trans_storage$0001 storage_ph:TrStoragePhase
      = TransactionDescr;

    trans_tick_tock$001 is_tock:Bool storage_ph:TrStoragePhase
      compute_ph:TrComputePhase action:(Maybe ^TrActionPhase)
      aborted:Bool destroyed:Bool = TransactionDescr;
      
    trans_split_prepare$0100 split_info:SplitMergeInfo
      storage_ph:(Maybe TrStoragePhase)
      compute_ph:TrComputePhase action:(Maybe ^TrActionPhase)
      aborted:Bool destroyed:Bool
      = TransactionDescr;
      
    trans_split_install$0101 split_info:SplitMergeInfo
      prepare_transaction:^Transaction
      installed:Bool = TransactionDescr;

    trans_merge_prepare$0110 split_info:SplitMergeInfo
      storage_ph:TrStoragePhase aborted:Bool
      = TransactionDescr;
      
    trans_merge_install$0111 split_info:SplitMergeInfo
      prepare_transaction:^Transaction
      storage_ph:(Maybe TrStoragePhase)
      credit_ph:(Maybe TrCreditPhase)
      compute_ph:TrComputePhase action:(Maybe ^TrActionPhase)
      aborted:Bool destroyed:Bool
      = TransactionDescr;
    """
    def __init__(self, cell_slice: Slice):
        prefix = cell_slice.read_next(3)
        if prefix == bitarray('001'):
            self._init_tick_tock(cell_slice)
        else:
            prefix += cell_slice.read_next(1)
            if prefix == bitarray('0000'):
                self._init_ord(cell_slice)
            elif prefix == bitarray('0001'):
                self._init_storage(cell_slice)
            elif prefix == bitarray('0100'):
                self._init_split_prepare(cell_slice)
            elif prefix == bitarray('0110'):
                self._init_merge_prepare(cell_slice)
            elif prefix == bitarray('0111'):
                self._init_merge_install(cell_slice)

    def _init_ord(self, cell_slice: Slice):
        self.type = 'trans_ord'
        self.credit_first = cell_slice.read_next(1).any()
        self.storage_ph = TrStoragePhase(cell_slice) if cell_slice.read_next(1).any() else None
        self.credit_ph = TrCreditPhase(cell_slice) if cell_slice.read_next(1).any() else None
        self.compute_ph = TrComputePhase(cell_slice)
        self.action = TrActionPhase(cell_slice.read_next_ref()) if cell_slice.read_next(1).any() else None
        self.aborted = cell_slice.read_next(1).any()
        self.bounce = TrBouncePhase(cell_slice) if cell_slice.read_next(1).any() else None
        self.destroyed = cell_slice.read_next(1).any()
    
    def _init_storage(self, cell_slice: Slice):
        self.type = 'trans_storage'
        self.storage_ph = TrStoragePhase(cell_slice)
    
    def _init_tick_tock(self, cell_slice: Slice):
        self.type = 'trans_tick_tock'
        self.is_tock = cell_slice.read_next(1).any()
        self.storage_ph = TrStoragePhase(cell_slice)
        self.compute_ph = TrComputePhase(cell_slice)
        self.action = TrActionPhase(cell_slice.read_next_ref()) if cell_slice.read_next(1).any() else None
        self.aborted = cell_slice.read_next(1).any()
        self.destroyed = cell_slice.read_next(1).any()
    
    def _init_split_prepare(self, cell_slice: Slice):
        self.type = 'trans_split_prepare'
        self.split_info = SplitMergeInfo(cell_slice)
        self.storage_ph = TrStoragePhase(cell_slice) if cell_slice.read_next(1).any() else None
        self.compute_ph = TrComputePhase(cell_slice)
        self.action = TrActionPhase(cell_slice.read_next_ref()) if cell_slice.read_next(1).any() else None
        self.aborted = cell_slice.read_next(1).any()
        self.destroyed = cell_slice.read_next(1).any()
        
    def _init_merge_prepare(self, cell_slice: Slice):
        self.type = 'trans_merge_prepare'
        self.split_info = SplitMergeInfo(cell_slice)
        self.storage_ph = TrStoragePhase(cell_slice)
        self.aborted = cell_slice.read_next(1).any()
    
    def _init_merge_install(self, cell_slice: Slice):
        self.type = 'trans_merge_install'
        self.split_info = SplitMergeInfo(cell_slice)
        self.prepare_transaction = Transaction(cell_slice.read_next_ref())
        self.storage_ph = TrStoragePhase(cell_slice) if cell_slice.read_next(1).any() else None
        self.credit_ph = TrCreditPhase(cell_slice) if cell_slice.read_next(1).any() else None
        self.compute_ph = TrComputePhase(cell_slice)
        self.action = TrActionPhase(cell_slice.read_next_ref()) if cell_slice.read_next(1).any() else None
        self.aborted = cell_slice.read_next(1).any()
        self.destroyed = cell_slice.read_next(1).any()
    
class AccountStatus:
    """
    acc_state_uninit$00 = AccountStatus;
    acc_state_frozen$01 = AccountStatus;
    acc_state_active$10 = AccountStatus;
    acc_state_nonexist$11 = AccountStatus;
    """
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(2)
        if prefix == bitarray('00'):
            self.type = 'acc_state_uninit'
        elif prefix == bitarray('01'):
            self.type = 'acc_state_frozen'
        elif prefix == bitarray('10'):
            self.type = 'acc_state_active'
        elif prefix == bitarray('11'):
            self.type = 'acc_state_nonexist'
class HASH_UPDATE:
    """
    update_hashes#72 {X:Type} old_hash:bits256 new_hash:bits256
      = HASH_UPDATE X;
    """
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(8)
        if prefix != bitarray('01110010'):
            raise ValueError(f'HASH_UPDATE must have prefix 0x72 (but has {prefix})')
        self.old_hash = ba2hex(cell_slice.read_next(256))
        self.new_hash = ba2hex(cell_slice.read_next(256))

class Transaction:
    """
    transaction$0111 account_addr:bits256 lt:uint64 
      prev_trans_hash:bits256 prev_trans_lt:uint64 now:uint32
      outmsg_cnt:uint15
      orig_status:AccountStatus end_status:AccountStatus
      ^[ in_msg:(Maybe ^(Message Any)) out_msgs:(HashmapE 15 ^(Message Any)) ]
      total_fees:CurrencyCollection state_update:^(HASH_UPDATE Account)
      description:^TransactionDescr = Transaction;
    """
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(4)
        if prefix != bitarray('0111'):
            raise ValueError(f'Transaction must have prefix 0111 (but has {prefix})')
            
        self.account_addr = ba2hex(cell_slice.read_next(256))
        self.lt = ba2int(cell_slice.read_next(64), signed=False)
        self.prev_trans_hash = ba2hex(cell_slice.read_next(256))
        self.prev_trans_lt = ba2int(cell_slice.read_next(64), signed=False)
        self.now = ba2int(cell_slice.read_next(32), signed=False)
        self.outmsg_cnt = ba2int(cell_slice.read_next(15), signed=False)
        
        self.orig_status = AccountStatus(cell_slice)
        self.end_status = AccountStatus(cell_slice)
        
        messages = cell_slice.read_next_ref() # TODO: parse messages
        
        self.total_fees = CurrencyCollection(cell_slice)
        
        state_update_cell_slice = cell_slice.read_next_ref() # TODO: parse state update
        self.state_update = HASH_UPDATE(state_update_cell_slice)
        state_update_cell_slice.raise_if_not_empty()
        
        description_cell_slice = cell_slice.read_next_ref()
        self.description = TransactionDescr(description_cell_slice)
        description_cell_slice.raise_if_not_empty()

class MsgAddress:
    def parse(cell_slice):
        prefix = cell_slice.prefetch_next(2)
        if prefix == bitarray('00') or prefix == bitarray('01'):
            return MsgAddressExt(cell_slice)
        else:
            return MsgAddressInt(cell_slice)

class MsgAddressExt:
    """
    addr_none$00 = MsgAddressExt;
    addr_extern$01 len:(## 9) external_address:(bits len) 
                = MsgAddressExt;
    """
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(2)
        if prefix == bitarray('00'):
            self.type = 'addr_none'
        elif prefix == bitarray('01'):
            self.type = 'addr_extern'
            cell_slice.read_next(cell_slice.bits_left()) #TODO: parse len and external_address

class MsgAddressInt:
    """
    anycast_info$_ depth:(#<= 30) { depth >= 1 }
        rewrite_pfx:(bits depth) = Anycast;
    addr_std$10 anycast:(Maybe Anycast) 
        workchain_id:int8 address:bits256  = MsgAddressInt;
    addr_var$11 anycast:(Maybe Anycast) addr_len:(## 9) 
        workchain_id:int32 address:(bits addr_len) = MsgAddressInt;
    """
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(2)
        if prefix == bitarray('10'):
            self.type = 'addr_std'
        elif prefix == bitarray('11'):
            self.type = 'addr_var'
        else:
            raise ValueError(f'MsgAddressInt must have prefix 10 or 11 (but has {prefix})')

        if cell_slice.read_next(1).any():
            raise NotImplementedError('Anycast not supported yet')

        if self.type == 'addr_std':
            self.workchain_id = ba2int(cell_slice.read_next(8), signed=True)
            self.address = ba2hex(cell_slice.read_next(256))
        else:
            addr_len = ba2int(cell_slice.read_next(6), signed=False)
            self.workchain_id = ba2int(cell_slice.read_next(32), signed=True)
            self.address = ba2hex(cell_slice.read_next(addr_len))

class TokenData:
    attributes = ['uri', 'name', 'description', 'image', 'image_data', 'symbol', 'decimals', 'amount_style', 'render_type']
    attributes_hashes = {}
    for attr in attributes:
        attributes_hashes[sha256(attr.encode('utf-8')).hexdigest()] = attr

    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(8)
        if prefix == bitarray('00000000'):
            self.type = 'onchain'
            if cell_slice.read_next(1).any():
                child_slice = cell_slice.read_next_ref()
                hashmap_cell = Cell()
                hashmap_cell.data.data = child_slice._data
                hashmap_cell.refs = child_slice._refs
                hashmap = {}
                parse_hashmap(hashmap_cell, 256, hashmap, bitarray())
                self.data = self._parse_attributes(hashmap)
            else:
                self.data = {}
        elif prefix == bitarray('00000001'):
            self.type = 'offchain'
            data = cell_slice.read_next(cell_slice.bits_left())
            while cell_slice.refs_left() > 0:
                cell_slice = cell_slice.read_next_ref()
                data += cell_slice.read_next(cell_slice.bits_left())
            self.data = data.tobytes().decode('ascii')
        else:
            raise ValueError('Unexpected content prefix')
    
    def _parse_attributes(self, hashmap: dict):
        res = {}
        for attr_hash_bitstr, value_cell in hashmap.items():
            attr_hash_hex = ba2hex(bitarray(attr_hash_bitstr))
            attr_name = TokenData.attributes_hashes.get(attr_hash_hex)
            if attr_name is None:
                attr_name = attr_hash_hex
            res[attr_name] = self._parse_content_data(value_cell)
        return res

    def _parse_content_data(self, cell: Cell, encoding='utf-8'):
        if len(cell.data.data) > 0:
             # TODO: Check if it complies with Token Data standard
            cell_slice = Slice(cell)
        else:
            cell_slice = Slice(cell.refs[0])
        prefix = cell_slice.read_next(8)
        if prefix == bitarray('00000000'):
            #snake
            data = cell_slice.read_next(cell_slice.bits_left())
            while cell_slice.refs_left() > 0:
                cell_slice = cell_slice.read_next_ref()
                data += cell_slice.read_next(cell_slice.bits_left())
            return data.tobytes().decode(encoding)
        elif prefix == bitarray('00000001'):
            #chunks
            data = bitarray()
            if cell_slice.read_next(1).any():
                child_slice = cell_slice.read_next_ref()
                hashmap_cell = Cell()
                hashmap_cell.data.data = child_slice._data
                hashmap_cell.refs = child_slice._refs
                hashmap = {}
                parse_hashmap(hashmap_cell, 32, hashmap, bitarray())
                for ind in range(len(hashmap)):
                    ind_bitstr = f'{ind:032b}'
                    chunk_cell = hashmap[ind_bitstr]
                    assert chunk_cell.data.data == bitarray()
                    assert len(chunk_cell.refs) == 1
                    data += chunk_cell.refs[0].data.data
        else:
            raise ValueError(f'Unexpected content data prefix: {prefix}')
        return data.tobytes().decode(encoding)


class DNSRecord:
    """
    dns_smc_address#9fd3 smc_addr:MsgAddressInt flags:(## 8) { flags <= 1 }
        cap_list:flags . 0?SmcCapList = DNSRecord;
    dns_next_resolver#ba93 resolver:MsgAddressInt = DNSRecord;
    dns_adnl_address#ad01 adnl_addr:bits256 flags:(## 8) { flags <= 1 }
        proto_list:flags . 0?ProtoList = DNSRecord;
    dns_storage_address#7473 bag_id:bits256 = DNSRecord;
    """
    def __init__(self, cell_slice):
        prefix = ba2hex(cell_slice.read_next(16))
        if prefix == '9fd3':
            self.smc_addr = MsgAddressInt(cell_slice)
            flags = ba2int(cell_slice.read_next(8))
            if flags & 1:
                #TODO: parse SmcCapList
                cell_slice.read_next(cell_slice.bits_left())
        elif prefix == 'ad01':
            self.adnl_addr = ba2hex(cell_slice.read_next(256))
            flags = ba2int(cell_slice.read_next(8))
            if flags & 1:
                #TODO: parse ProtoList
                cell_slice.read_next(cell_slice.bits_left())
        elif prefix == 'ba93':
            self.resolver = MsgAddressInt(cell_slice)
        elif prefix == '7473':
            self.bag_id = ba2hex(cell_slice.read_next(256))
        else:
            raise ValueError(f'Unexpected content data prefix: {prefix}')

class DNSRecordSet:
    attributes = ['wallet', 'site', 'storage', 'dns_next_resolver']
    attributes_hashes = {}
    for attr in attributes:
        attributes_hashes[sha256(attr.encode('utf-8')).hexdigest()] = attr

    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(8)
        assert prefix == bitarray('00000000'), 'dns data expected to be onchain'
        if cell_slice.read_next(1).any():
            child_slice = cell_slice.read_next_ref()
            hashmap_cell = Cell()
            hashmap_cell.data.data = child_slice._data
            hashmap_cell.refs = child_slice._refs
            hashmap = {}
            parse_hashmap(hashmap_cell, 256, hashmap, bitarray())
            self.data = self._parse_attributes(hashmap)
        else:
            self.data = {}
                
    def _parse_attributes(self, hashmap: dict):
        res = {}
        for attr_hash_bitstr, value_cell in hashmap.items():
            attr_hash_hex = ba2hex(bitarray(attr_hash_bitstr))
            attr_name = DNSRecordSet.attributes_hashes.get(attr_hash_hex)
            if attr_name is None:
                attr_name = attr_hash_hex
            assert len(value_cell.refs) == 1, 'dict val should contain exact 1 ref'
            res[attr_name] = DNSRecord(Slice(value_cell.refs[0]))
        return res

class TextCommentMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(32)
        if prefix != hex2ba('00000000'):
            raise ValueError('Unexpected content prefix')
        if cell_slice.prefetch_next(8) == hex2ba('ff'):
            raise ValueError('Text comment cannot start with byte 0xff')
        data = cell_slice.read_next(cell_slice.bits_left()).tobytes()
        self.text_comment = codecs.decode(data, 'utf8')
        while cell_slice.refs_left() > 0:
            if cell_slice.refs_left() > 1:
                raise ValueError('Unexpected number of subcells in simple comment message')
            cell_slice = cell_slice.read_next_ref()
            data = cell_slice.read_next(cell_slice.bits_left()).tobytes()
            self.text_comment += codecs.decode(data, 'utf8')

        self.text_comment = self.text_comment.replace('\x00', '')

class BinaryCommentMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(40)
        if prefix != hex2ba('00000000ff'):
            raise ValueError('Unexpected content prefix')
        data_ba = cell_slice.read_next(cell_slice.bits_left())
        while cell_slice.refs_left() > 0:
            if cell_slice.refs_left() > 1:
                raise ValueError('Unexpected number of subcells in binary comment message')
            cell_slice = cell_slice.read_next_ref()
            data_ba += cell_slice.read_next(cell_slice.bits_left())
        self.hex_comment = ba2hex(data_ba)

class CommentMessage:
    @classmethod
    def parse(cls, cell_slice: Slice):
        if cell_slice.prefetch_next(32) != hex2ba('00000000'):
            raise ValueError('Unexpected content prefix')
        if cell_slice.bits_left() >= 40 and cell_slice.prefetch_next(40)[32:40] == hex2ba('ff'):
            return BinaryCommentMessage(cell_slice)
        else:
            return TextCommentMessage(cell_slice)

class NftTransferMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(32)
        if prefix != hex2ba('5fcc3d14'):
            raise ValueError('Unexpected content prefix')
        self.query_id = ba2int(cell_slice.read_next(64), signed=False)
        self.new_owner = MsgAddress.parse(cell_slice)
        self.response_destination = MsgAddress.parse(cell_slice)
        if cell_slice.read_next(1).any():
            cell_slice.read_next_ref() #TODO: read custom_payload
        self.forward_amount = cell_slice.read_var_uint(16)
        if cell_slice.read_next(1).any():  #TODO: read forward_payload
            cell_slice.read_next_ref()
        else:
            cell_slice.read_next(cell_slice.bits_left())

class NftOwnershipAssignedMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(32)
        if prefix != hex2ba('05138d91'):
            raise ValueError('Unexpected content prefix')
        self.query_id = ba2int(cell_slice.read_next(64), signed=False)
        self.prev_owner = MsgAddress.parse(cell_slice)
        if cell_slice.read_next(1).any():  #TODO: read forward_payload
            cell_slice.read_next_ref()
        else:
            cell_slice.read_next(cell_slice.bits_left())

class NftExcessesMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(32)
        if prefix != hex2ba('d53276db'):
            raise ValueError('Unexpected content prefix')
        self.query_id = ba2int(cell_slice.read_next(64), signed=False)

class NftGetStaticDataMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(32)
        if prefix != hex2ba('2fcb26a2'):
            raise ValueError('Unexpected content prefix')
        self.query_id = ba2int(cell_slice.read_next(64), signed=False)

class NftReportStaticDataMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(32)
        if prefix != hex2ba('8b771735'):
            raise ValueError('Unexpected content prefix')
        self.query_id = ba2int(cell_slice.read_next(64), signed=False)
        self.index = ba2int(cell_slice.read_next(256), signed=False)
        self.collection = MsgAddress.parse(cell_slice)

class JettonTransferMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(32)
        if prefix != hex2ba('0f8a7ea5'):
            raise ValueError('Unexpected content prefix')
        self.query_id = ba2int(cell_slice.read_next(64), signed=False)
        self.amount = cell_slice.read_var_uint(16)
        self.destination = MsgAddress.parse(cell_slice)
        self.response_destination = MsgAddress.parse(cell_slice)
        if cell_slice.read_next(1).any():
            cell_slice.read_next_ref()  #TODO: read custom_payload
        self.forward_ton_amount = cell_slice.read_var_uint(16)
        if cell_slice.read_next(1).any():  #TODO: read forward_payload
            cell_slice.read_next_ref()
        else:
            cell_slice.read_next(cell_slice.bits_left())


class JettonTransferNotificationMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(32)
        if prefix != hex2ba('7362d09c'):
            raise ValueError('Unexpected content prefix')
        self.query_id = ba2int(cell_slice.read_next(64), signed=False)
        self.amount = cell_slice.read_var_uint(16)
        self.sender = MsgAddress.parse(cell_slice)
        if cell_slice.read_next(1).any():  #TODO: read forward_payload
            cell_slice.read_next_ref()
        else:
            cell_slice.read_next(cell_slice.bits_left())


class JettonExcessesMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(32)
        if prefix != hex2ba('d53276db'):
            raise ValueError('Unexpected content prefix')
        self.query_id = ba2int(cell_slice.read_next(64), signed=False)

class JettonBurnMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(32)
        if prefix != hex2ba('595f07bc'):
            raise ValueError('Unexpected content prefix')
        self.query_id = ba2int(cell_slice.read_next(64), signed=False)
        self.amount = cell_slice.read_var_uint(16)
        self.response_destination = MsgAddress.parse(cell_slice)
        if cell_slice.read_next(1).any():
            cell_slice.read_next_ref()  #TODO: read custom_payload

class JettonInternalTransferMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(32)
        if prefix != hex2ba('178d4519'):
            raise ValueError('Unexpected content prefix')
        self.query_id = ba2int(cell_slice.read_next(64), signed=False)
        self.amount = cell_slice.read_var_uint(16)
        self.from_ = MsgAddress.parse(cell_slice)
        self.response_address = MsgAddress.parse(cell_slice)
        self.forward_ton_amount = cell_slice.read_var_uint(16)
        if cell_slice.read_next(1).any():  #TODO: read forward_payload
            cell_slice.read_next_ref()
        else:
            cell_slice.read_next(cell_slice.bits_left())

class JettonBurnNotificationMessage:
    def __init__(self, cell_slice):
        prefix = cell_slice.read_next(32)
        if prefix != hex2ba('7bdd97de'):
            raise ValueError('Unexpected content prefix')
        self.query_id = ba2int(cell_slice.read_next(64), signed=False)
        self.amount = cell_slice.read_var_uint(16)
        self.sender = MsgAddress.parse(cell_slice)
        self.response_destination = MsgAddress.parse(cell_slice)

# Deprecated, use boc_to_object
def parse_transaction(b64_tx_data: str) -> dict:
    transaction_boc = codecs.decode(codecs.encode(b64_tx_data, 'utf-8'), 'base64')
    cell = deserialize_boc(transaction_boc)
    cell_slice = Slice(cell)
    tx = Transaction(cell_slice)
    cell_slice.raise_if_not_empty()

    return json.loads(json.dumps(tx, default=lambda o: o.__dict__))

# Deprecated, use boc_to_object
def parse_tlb_object(b64_boc: str, tlb_type: type):
    boc = codecs.decode(codecs.encode(b64_boc, 'utf-8'), 'base64')
    cell = deserialize_boc(boc)
    cell_slice = Slice(cell)
    parse_cons = getattr(tlb_type, "parse", None)
    if callable(parse_cons):
        object = parse_cons(cell_slice)
    else:
        object = tlb_type(cell_slice)
    cell_slice.raise_if_not_empty()
    return json.loads(json.dumps(object, default=lambda o: o.__dict__))

def boc_to_object(b64_boc: str, tlb_type: type):
    boc = codecs.decode(codecs.encode(b64_boc, 'utf-8'), 'base64')
    cell = deserialize_boc(boc)
    cell_slice = Slice(cell)
    parse_cons = getattr(tlb_type, "parse", None)
    if callable(parse_cons):
        object = parse_cons(cell_slice)
    else:
        object = tlb_type(cell_slice)
    cell_slice.raise_if_not_empty()
    return object