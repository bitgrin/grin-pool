import React, { Component } from 'react'
import { Table } from 'reactstrap'
import { secondsToHms, nanoGrinToGrin } from '../../utils/utils.js'

export class MinerPaymentDataComponent extends Component {
  constructor (props) {
    super(props)
    this.state = {
      faderStyleId: 'balanceChange1'
    }
  }

  UNSAFE_componentWillMount () {
    this.fetchMinerPaymentData()
  }

  componentDidUpdate (prevProps) {
    const { lastestBlockHeight } = this.props
    const { faderStyleId } = this.state
    if (prevProps.lastestBlockHeight !== lastestBlockHeight) {
      this.fetchMinerPaymentData()
      this.setState({
        faderStyleId: faderStyleId === 'balanceChange1' ? 'balanceChange2' : 'balanceChange1'
      })
    }
  }

  fetchMinerPaymentData = () => {
    const { fetchMinerPaymentData, fetchMinerImmatureBalance } = this.props
    fetchMinerPaymentData()
    fetchMinerImmatureBalance()
  }

  render () {
    const {
      amount,
      address,
      lastSuccess,
      failureCount,
      lastTry,
      minerImmatureBalance,
      currentTimestamp
    } = this.props
    const { faderStyleId } = this.state
    const readableAmount = amount > 0 ? amount : 0
    const lastTryTimeAgo = lastTry ? secondsToHms(currentTimestamp - lastTry) : 'n/a'
    const lastPayoutTimeAgo = lastSuccess ? secondsToHms(currentTimestamp - lastSuccess) : 'n/a'
    const minerImmatureBalanceSyntax = (!isNaN(minerImmatureBalance) && minerImmatureBalance > 0) ? `${nanoGrinToGrin(minerImmatureBalance)} XBG` : 'n/a'
    return (
      <div>
        <h4>Payment Info</h4>
        <Table size='sm'>
          <tbody>
            <tr>
              <td>Available for withdrawal</td>
              <td>{nanoGrinToGrin(readableAmount)} XBG</td>
            </tr>
            <tr>
              <td>Estimate unmatured earnings <div className="Thetooltip">(?)<span className="tooltiptext">On the Bitgrin network freshly mined coins mature after being mined for 24 hours. This is a ballpark figure, its notoriously hard to estimate on a completely private and opaque blockchain.</span></div></td>
              <td id={faderStyleId}>{minerImmatureBalanceSyntax} XBG</td>
            </tr>
            <tr>
              <td>Payout Address</td>
              <td>{address || 'n/a'}</td>
            </tr>
            <tr>
              <td>Last Payout</td>
              <td>{lastPayoutTimeAgo || 'n/a'}</td>
            </tr>
            <tr>
              <td>Payout Attempt Failures</td>
              <td>{failureCount}</td>
            </tr>
            <tr>
              <td>Last Auto Payout Attempt</td>
              <td>{lastTryTimeAgo}</td>
            </tr>
          </tbody>
        </Table>
      </div>
    )
  }
}
