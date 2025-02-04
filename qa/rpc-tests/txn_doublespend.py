#!/usr/bin/env python
# Copyright (c) 2014 The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

#
# Test proper accounting with malleable transactions
#

import sys; assert sys.version_info < (3,), ur"This script does not run under Python 3. Please use Python 2.7.x."

from test_framework.test_framework import BitcoinTestFramework
from test_framework.authproxy import JSONRPCException
from test_framework.util import assert_equal, connect_nodes, \
    sync_blocks, gather_inputs, initialize_chain_clean, start_nodes, \
    connect_nodes_bi

class TxnMallTest(BitcoinTestFramework):

    def add_options(self, parser):
        parser.add_option("--mineblock", dest="mine_block", default=False, action="store_true",
                          help="Test double-spend of 1-confirmed transaction")

    #def setup_network(self):
        # Start with split network:
    #    return super(TxnMallTest, self).setup_network(True)

    def setup_chain(self):
        print("Initializing test directory "+self.options.tmpdir)
        initialize_chain_clean(self.options.tmpdir, 4)

    def setup_network(self, split=False):
        self.nodes = start_nodes(4, self.options.tmpdir, extra_args=[["-debug=zrpcunsafe", "-txindex"]] * 4 )
        connect_nodes_bi(self.nodes,0,1)
        connect_nodes_bi(self.nodes,1,2)
        connect_nodes_bi(self.nodes,0,2)
        connect_nodes_bi(self.nodes,0,3)
        self.is_network_split=False
        self.sync_all()
        self.nodes[0].generate(25)
        self.sync_all()
        self.nodes[1].generate(25)
        self.sync_all()
        self.nodes[2].generate(25)
        self.sync_all()
        self.nodes[3].generate(25)
        self.sync_all()
        self.nodes[0].generate(720)
        self.sync_all()

    def run_test(self):
        mining_reward = 10
        starting_balance = mining_reward * 25

        for i in range(4):
            assert_equal(self.nodes[i].getbalance(), starting_balance)
            self.nodes[i].getnewaddress("")  # bug workaround, coins generated assigned to first getnewaddress!

        # Coins are sent to node1_address
        node1_address = self.nodes[1].getnewaddress("")

        # First: use raw transaction API to send (starting_balance - (mining_reward - 2)) BTC to node1_address,
        # but don't broadcast:
        (total_in, inputs) = gather_inputs(self.nodes[0], (starting_balance - (mining_reward - 2)))
        change_address = self.nodes[0].getnewaddress("")
        outputs = {}
        outputs[change_address] = (mining_reward - 2)
        outputs[node1_address] = (starting_balance - (mining_reward - 2))
        rawtx = self.nodes[0].createrawtransaction(inputs, outputs)
        doublespend = self.nodes[0].signrawtransaction(rawtx)
        assert_equal(doublespend["complete"], True)

        # Create two transaction from node[0] to node[1]; the
        # second must spend change from the first because the first
        # spends all mature inputs:
        txid1 = self.nodes[0].sendfrom("", node1_address, (starting_balance - (mining_reward - 2)), 0)
        txid2 = self.nodes[0].sendfrom("", node1_address, 5, 0)

        # Have node0 mine a block:
        if (self.options.mine_block):
            self.nodes[0].generate(1)
            sync_blocks(self.nodes[0:2])

        tx1 = self.nodes[0].gettransaction(txid1)
        tx2 = self.nodes[0].gettransaction(txid2)

        # Node0's balance should be starting balance, plus mining_reward for another
        # matured block, minus (starting_balance - (mining_reward - 2)), minus 5, and minus transaction fees:
        expected = starting_balance
        if self.options.mine_block: expected += mining_reward
        expected += tx1["amount"] + tx1["fee"]
        expected += tx2["amount"] + tx2["fee"]
        assert_equal(self.nodes[0].getbalance(), expected)

        if self.options.mine_block:
            assert_equal(tx1["confirmations"], 1)
            assert_equal(tx2["confirmations"], 1)
            # Node1's total balance should be its starting balance plus both transaction amounts:
            assert_equal(self.nodes[1].getbalance(""), starting_balance - (tx1["amount"]+tx2["amount"]))
        else:
            assert_equal(tx1["confirmations"], 0)
            assert_equal(tx2["confirmations"], 0)

        if self.options.mine_block:
            try:
                # Now give doublespend to miner, inputs already spent
                self.nodes[2].sendrawtransaction(doublespend["hex"])
                assert(False)
            except JSONRPCException as e:
                errorString = e.error['message']
                assert("Missing inputs" in errorString)
        else:
            # Now give doublespend to miner:
            self.nodes[2].sendrawtransaction(doublespend["hex"])
            # ... mine a block...
            self.nodes[2].generate(1)

            # Reconnect the split network, and sync chain:
            connect_nodes(self.nodes[1], 2)
            self.nodes[2].generate(1)  # Mine another block to make sure we sync
            sync_blocks(self.nodes)

            # Re-fetch transaction info:
            tx1 = self.nodes[0].gettransaction(txid1)
            tx2 = self.nodes[0].gettransaction(txid2)

            # Both transactions should be conflicted
            assert_equal(tx1["confirmations"], -1)
            assert_equal(tx2["confirmations"], -1)

            # Node0's total balance should be starting balance, plus (mining_reward * 2) for
            # two more matured blocks, minus (starting_balance - (mining_reward - 2)) for the double-spend:
            expected = starting_balance + (mining_reward * 2) - (starting_balance - (mining_reward - 2))
            assert_equal(self.nodes[0].getbalance(), expected)
            assert_equal(self.nodes[0].getbalance("*"), expected)

            # Node1's total balance should be its starting balance plus the amount of the mutated send:
            assert_equal(self.nodes[1].getbalance(""), starting_balance + (starting_balance - (mining_reward - 2)))

if __name__ == '__main__':
    TxnMallTest().main()
