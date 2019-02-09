import React, { Component } from 'react'
import { Col, Card, CardBody } from 'reactstrap'

export class AboutComponent extends Component {
  render () {
    return (
      <Col>
        <Card>
          <CardBody>
            <div className='card__title'>
              <h5 className='bold-text'>Open-Source Mining Pool for the MimbleWimble BitGrin Blockchain</h5>
            </div>
            <h4 className='bold-text'>About BitGrinPool</h4>
            <p style={{ fontWeight: 'bold' }}>BitGrin is currently mining on MainNet.</p>
            <h4>How to mine in this pool:</h4>
            <ul>
              <li>Supports Linux and Windows miners: mimblewimble/bitgrin/grin-miner and mozkomor/GrinGoldMiner</li>
              <li><a href="https://bitgrin.io/bitgrinpool-cpu-mining-tutorial/">CPU Mining Guide</a></li>
              <li><a href="https://bitgrin.io/bitgrinpool-gpu-mining-tutorial/">GPU Mining Guide</a></li>
              <li><a href="https://medium.com/@blade.doyle/configure-payments-on-mwgrinpool-com-how-to-7b84163ec467">Payment Configuration Guide</a></li>
              <li><a href="https://t.me/BitGrinCommunity">BitGrin Telegram Group</a></li>
            </ul>
          </CardBody>
        </Card>
      </Col>
    )
  }
}
