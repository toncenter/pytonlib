from pytonlib.utils.tlb import parse_tlb_object, MsgAddress, MsgAddressInt, TokenData, DNSRecordSet
from pytonlib.utils.address import detect_address

def read_stack_num(entry: list):
    assert entry[0] == 'num'
    return int(entry[1], 16)

def read_stack_cell(entry: list):
    assert entry[0] == 'cell'
    return entry[1]['bytes']

def parse_jetton_master_data(stack: list):
    total_supply = read_stack_num(stack[0])
    mintable = bool(read_stack_num(stack[1]))
    admin_address = parse_tlb_object(read_stack_cell(stack[2]), MsgAddress)
    if admin_address['type'] == 'addr_std':
        admin_address_friendly = detect_address(f"{admin_address['workchain_id']}:{admin_address['address']}")['bounceable']['b64url']
    elif admin_address['type'] == 'addr_none':
        admin_address_friendly = None
    else:
        raise NotImplementedError('Owner address not supported')

    jetton_content = parse_tlb_object(read_stack_cell(stack[3]), TokenData)
    jetton_wallet_code = read_stack_cell(stack[4])
    return {
        'total_supply': total_supply,
        'mintable': mintable,
        'admin_address': admin_address_friendly,
        'jetton_content': jetton_content,
        'jetton_wallet_code': jetton_wallet_code
    }

def parse_jetton_wallet_data(stack: list):
    balance = read_stack_num(stack[0])
    owner = parse_tlb_object(read_stack_cell(stack[1]), MsgAddress)
    if owner['type'] == 'addr_std':
        owner_friendly = detect_address(f"{owner['workchain_id']}:{owner['address']}")['bounceable']['b64url']
    else:
        raise NotImplementedError('Owner address not supported')

    jetton = parse_tlb_object(read_stack_cell(stack[2]), MsgAddress)
    if jetton['type'] == 'addr_std':
        jetton_friendly = detect_address(f"{jetton['workchain_id']}:{jetton['address']}")['bounceable']['b64url']
    else:
        raise NotImplementedError('Jetton address not supported')
    jetton_wallet_code = read_stack_cell(stack[3])
    return {
        'balance': balance,
        'owner': owner_friendly,
        'jetton': jetton_friendly,
        'jetton_wallet_code': jetton_wallet_code
    }

def parse_single_address_stack(stack: list):
    jetton_wallet_address = parse_tlb_object(read_stack_cell(stack[0]), MsgAddress)
    if jetton_wallet_address['type'] == 'addr_std':
        jetton_wallet_address_friendly = detect_address(f"{jetton_wallet_address['workchain_id']}:{jetton_wallet_address['address']}")['bounceable']['b64']
    else:
        raise NotImplementedError('addr_var jetton wallet address not supported')
    return jetton_wallet_address_friendly

def parse_jetton_wallet_address_data(stack: list):
    return parse_single_address_stack(stack)

def parse_nft_item_address_data(stack: list):
    return parse_single_address_stack(stack)

def parse_nft_collection_data(stack: list):
    next_item_index = read_stack_num(stack[0])
    collection_content = parse_tlb_object(read_stack_cell(stack[1]), TokenData)
    owner_address = parse_tlb_object(read_stack_cell(stack[2]), MsgAddress)
    if owner_address['type'] == 'addr_std':
        owner_address_friendly = detect_address(f"{owner_address['workchain_id']}:{owner_address['address']}")['bounceable']['b64url']
    elif owner_address['type'] == 'addr_none':
        owner_address_friendly = None
    else:
        raise NotImplementedError('Owner address not supported')
    return {
        'next_item_index': next_item_index,
        'collection_content': collection_content,
        'owner_address': owner_address_friendly
    }

def parse_nft_item_data(stack: list):
    init = bool(read_stack_num(stack[0]))
    index = read_stack_num(stack[1])

    collection_address = parse_tlb_object(read_stack_cell(stack[2]), MsgAddress)
    if collection_address['type'] == 'addr_std':
        collection_address_friendly = detect_address(f"{collection_address['workchain_id']}:{collection_address['address']}")['bounceable']['b64url']
    elif collection_address['type'] == 'addr_none':
        collection_address_friendly = None
    else:
        raise NotImplementedError('Collection address not supported')

    owner_address = parse_tlb_object(read_stack_cell(stack[3]), MsgAddress)
    if owner_address['type'] == 'addr_std':
        owner_address_friendly = detect_address(f"{owner_address['workchain_id']}:{owner_address['address']}")['bounceable']['b64url']
    elif owner_address['type'] == 'addr_none':
        owner_address_friendly = None
    else:
        raise NotImplementedError('Owner address not supported')

    if collection_address['type'] == 'addr_none':
        individual_content = parse_tlb_object(read_stack_cell(stack[4]), TokenData)
    else:
        individual_content = read_stack_cell(stack[4])
    return {
        'init': init,
        'index': index,
        'owner_address': owner_address_friendly,
        'collection_address': collection_address_friendly,
        'individual_content': individual_content
    }

def parse_nft_content(stack: list):
    return parse_tlb_object(read_stack_cell(stack[0]), TokenData)

def parse_dns_content(stack: list):
    return parse_tlb_object(read_stack_cell(stack[0]), DNSRecordSet)
