import React, { Component } from 'react'
import { Col, Container, Row, Card, CardBody } from 'reactstrap'
import ReactGA from 'react-ga'

export class InstructionsComponent extends Component {
  constructor (props) {
    super(props)
    ReactGA.initialize('UA-132063819-1')
    ReactGA.pageview(window.location.pathname + window.location.search)
  }

  render () {
    return (
      <Container className='dashboard instructions'>
        <Row>
          <Col xs={12} md={12} lg={12} xl={12}>
            <h1 className='page-title'>Instructions</h1>
          </Col>
        </Row>
        <Card>
          <CardBody>
            <Row>
              <Col xs={12} md={9} lg={9} xl={9}>
                <h2>How to Mine BitGrin Tutorials</h2>
                <p style={{ fontSize: '1.1rem' }}>For those who want to mine on Windows, please check out our written tutorial <a href='https://bitgrin.io/windowsmining/' rel='noopener noreferrer' target='_blank'>here</a>.</p>
                <p style={{ fontSize: '1.1rem' }}>For those of you who want to GPU mine on Linux, please check out our written tutorial <a href='https://bitgrin.io/bitgrinpool-gpu-mining-tutorial/' rel='noopener noreferrer' target='_blank'>here</a>.</p>
              </Col>
              <Col xs={12} md={3} lg={3} xl={3}>
                <div className='article-tutorial-thumbnail'>
                  <a href='https://bitgrin.io/bitgrinpool-gpu-mining-tutorial/'><img src='/img/gpu-medium-article-overlayed.png' /></a>
                </div>
              </Col>
            </Row>
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <Row>
              <Col xs={12} md={9} lg={9} xl={9}>
                <h2>How to Configure Pool Payouts</h2>
                <p style={{ fontSize: '1.1rem' }}>To learn how to properly inititate pool payments, please read our tutorial <a href='https://bitgrin.io/bitgrin-pool-payments-guide/' rel='noopener noreferrer' target='_blank'>here</a></p>
              </Col>
              <Col xs={12} md={3} lg={3} xl={3}>
                <div className='article-tutorial-thumbnail'>
                  <a href='https://bitgrin.io/bitgrin-pool-payments-guide/'><img src='/img/payments-medium-article-overlayed.png' /></a>
                </div>
              </Col>
            </Row>
          </CardBody>
        </Card>
      </Container>
    )
  }
}
